import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type RefObject,
  type SetStateAction,
} from 'react'

import * as agentApi from '@/api/agent'
import type { FileInfo } from '@/api/file'
import type { ToolPanelHandle } from '@/components/ToolPanel'
import { usePendingMessage } from '@/hooks/usePendingMessage'
import {
  type AgentSSEEvent,
  type ErrorEventData,
  type MessageEventData,
  type PlanEventData,
  type TaskEventData,
  type TitleEventData,
  type ToolEventData,
} from '@/types/event'
import { type Message, type ToolContent } from '@/types/message'
import { SessionStatus } from '@/types/response'
import {
  reduceAppendUserAttachments,
  reduceAppendUserMessage,
  reduceError,
  reduceMessage,
  reduceTask,
  reduceTool,
  reduceTruncateAtUserEvent,
} from '@/lib/messageReducer'
import { showErrorToast } from '@/utils/toast'

export interface ChatStream {
  messages: Message[]
  plan: PlanEventData | undefined
  planHistory: PlanEventData[]
  viewedPlanIndex: number
  setViewedPlanIndex: Dispatch<SetStateAction<number>>

  title: string
  isLoading: boolean
  awaitingReply: boolean
  setAwaitingReply: Dispatch<SetStateAction<boolean>>
  realTime: boolean
  setRealTime: Dispatch<SetStateAction<boolean>>

  shareMode: 'private' | 'public'
  setShareMode: Dispatch<SetStateAction<'private' | 'public'>>

  lastNoMessageTool: RefObject<ToolContent | undefined>

  chat: (message?: string, files?: FileInfo[]) => void
  endChat: () => void
  handleEditUserMessage: (eventId: string, newMessage: string) => Promise<void>
  isLiveTool: (tool: ToolContent) => boolean
}

interface Options {
  sessionId: string | undefined
  /** Tool-panel handle the hook drives during live updates and on restore. */
  toolPanelRef: RefObject<ToolPanelHandle | null>
  /** Called once on session change so the page can drop file-panel UI. */
  onSessionChanged?: () => void
}

/**
 * Owns the live SSE chat lifecycle for a session: event reducer, in-flight
 * guards, replay-vs-live distinction, plan-history bookkeeping. Extracted
 * from the original ChatPage which had grown to ~1200 lines and tangled
 * presentation with stream state.
 *
 * Contract:
 *   - Mounts and tears down on `sessionId` change
 *   - Takes the `usePendingMessage` handoff exactly once for the new
 *     sessionId; otherwise restores from server history
 *   - Single tear-down path (`endChat`) shared by every "stream done"
 *     trigger so the in-flight flag can never desync from the SSE handle
 */
export function useChatStream({ sessionId, toolPanelRef, onSessionChanged }: Options): ChatStream {
  const [messages, setMessages] = useState<Message[]>([])
  const [plan, setPlan] = useState<PlanEventData | undefined>()
  const [planHistory, setPlanHistory] = useState<PlanEventData[]>([])
  const [viewedPlanIndex, setViewedPlanIndex] = useState(0)
  const [title, setTitle] = useState('New Chat')
  const [isLoading, setIsLoading] = useState(false)
  const [awaitingReply, setAwaitingReply] = useState(false)
  const [realTime, setRealTime] = useState(true)
  const [shareMode, setShareMode] = useState<'private' | 'public'>('private')

  const lastNoMessageTool = useRef<ToolContent | undefined>()
  const lastEventId = useRef<string | undefined>()
  const chatHandleRef = useRef<{ cancel: () => void } | null>(null)
  // Sync flag tracking whether a chat() invocation is already in flight.
  // Set the moment chat() starts, cleared in endChat. The ref check at the
  // top of chat() drops a second call (StrictMode remount, double-clicked
  // Send button, SSE reconnect race) before any HTTP POST is issued.
  const chatInFlightRef = useRef(false)
  // True only while restoreSession is synchronously replaying historical
  // events. Kept distinct from `realTime` (which also flips when the user
  // clicks a tool to view history) so terminal events from a live agent
  // still tear down the loading spinner correctly.
  const replayingRef = useRef(false)
  const initializedSessionRef = useRef<string | undefined>()

  const realTimeRef = useRef(realTime)
  useEffect(() => { realTimeRef.current = realTime }, [realTime])

  const isLiveTool = useCallback((tool: ToolContent): boolean => {
    if (tool.status === 'calling') return true
    if (tool.tool_call_id !== lastNoMessageTool.current?.tool_call_id) return false
    return tool.timestamp > Date.now() - 5 * 60 * 1000
  }, [])

  const handleMessageEvent = useCallback((data: MessageEventData) => {
    setMessages((prev) => reduceMessage(prev, data))
  }, [])

  const handleToolEvent = useCallback((data: ToolEventData) => {
    const tool: ToolContent = { ...data }
    setMessages((prev) => reduceTool(prev, data))
    if (tool.name !== 'message') {
      lastNoMessageTool.current = tool
      if (realTimeRef.current) toolPanelRef.current?.showToolPanel(tool, true)
    }
  }, [toolPanelRef])

  const handleTaskEvent = useCallback((data: TaskEventData) => {
    setMessages((prev) => reduceTask(prev, data))
    // Mirror task transitions into PlanPanel's snapshot — backend only
    // emits PlanEvent at plan-level transitions, so without this the plan
    // panel would show all tasks pending until the entire plan finished.
    // Skip during replay: a session restore already includes the plan
    // events that carry the canonical task statuses, and mirroring per-
    // task during replay stacks render pressure that has tripped React's
    // "Maximum update depth" guard on long sessions.
    if (replayingRef.current) return
    const mergeIntoPlan = (p: PlanEventData): PlanEventData => {
      if (p.plan_id !== data.plan_id) return p
      const idx = p.tasks.findIndex((t) => t.task_id === data.task_id)
      const merged: TaskEventData = {
        ...(idx >= 0 ? p.tasks[idx] : ({} as TaskEventData)),
        ...data,
      }
      const tasks =
        idx >= 0
          ? p.tasks.map((t, i) => (i === idx ? merged : t))
          : [...p.tasks, merged].sort((a, b) => a.position - b.position)
      return { ...p, tasks }
    }
    setPlan((prev) => (prev ? mergeIntoPlan(prev) : prev))
    // Also patch planHistory — ChatPage renders the active plan from
    // `planHistory[viewedPlanIndex]` (with `plan` only as a fallback),
    // so mirroring solely into `plan` left the top summary stuck at
    // 0/N until the closing PlanEvent overwrote the snapshot.
    setPlanHistory((prev) => {
      const idx = prev.findIndex((p) => p.plan_id === data.plan_id)
      if (idx < 0) return prev
      const next = prev.slice()
      next[idx] = mergeIntoPlan(prev[idx])
      return next
    })
  }, [])

  const handleErrorEvent = useCallback((data: ErrorEventData) => {
    setIsLoading(false)
    setMessages((prev) => reduceError(prev, data))
  }, [])

  const endChat = useCallback(() => {
    chatHandleRef.current?.cancel()
    chatHandleRef.current = null
    chatInFlightRef.current = false
    setIsLoading(false)
  }, [])

  const handleEvent = useCallback(
    (event: AgentSSEEvent) => {
      switch (event.event) {
        case 'message':
          handleMessageEvent(event.data as MessageEventData)
          break
        case 'tool':
          handleToolEvent(event.data as ToolEventData)
          break
        case 'task':
          handleTaskEvent(event.data as TaskEventData)
          break
        case 'error':
          handleErrorEvent(event.data as ErrorEventData)
          break
        case 'title':
          setTitle((event.data as TitleEventData).title)
          break
        case 'plan': {
          const planData = event.data as PlanEventData
          setPlan(planData)
          setPlanHistory((prev) => {
            const idx = prev.findIndex((p) => p.plan_id === planData.plan_id)
            if (idx >= 0) {
              const next = prev.slice()
              next[idx] = planData
              return next
            }
            return [planData, ...prev]
          })
          setViewedPlanIndex(0)
          break
        }
        case 'done':
        case 'wait':
          // Explicit terminal events — sse-starlette keeps the SSE open
          // with keep-alive pings, so onClose isn't reliable. Skip during
          // replay so an old `done` event in session history doesn't
          // cancel the brand-new chat() SSE that just started.
          if (!replayingRef.current) {
            setAwaitingReply(event.event === 'wait')
            endChat()
          }
          break
        default:
          break
      }
      // Don't advance lastEventId during replay — the resume cursor we
      // send back to the server should always reflect the freshest live
      // event we saw, not whatever the bounded history happened to end
      // on.
      if (!replayingRef.current) {
        lastEventId.current = event.data.event_id
      }
    },
    [handleMessageEvent, handleToolEvent, handleTaskEvent, handleErrorEvent, endChat],
  )

  const chat = useCallback(
    (message = '', files: FileInfo[] = []) => {
      if (!sessionId) return
      // Synchronous in-flight guard — set BEFORE issuing the request so two
      // near-simultaneous callers (StrictMode remount, double-clicked Send)
      // can't both fire the HTTP POST and create two parallel Plans on the
      // server.
      if (chatInFlightRef.current) {
        console.debug('[chat] dropped duplicate invocation while in flight')
        return
      }
      chatInFlightRef.current = true
      chatHandleRef.current?.cancel()
      chatHandleRef.current = null

      const ts = Math.floor(Date.now() / 1000)
      if (message.trim()) {
        setMessages((prev) => reduceAppendUserMessage(prev, message, ts))
      }
      if (files.length > 0) {
        setMessages((prev) => reduceAppendUserAttachments(prev, files, ts))
      }

      setIsLoading(true)

      const handle = agentApi.chatWithSession(
        sessionId,
        message,
        lastEventId.current,
        files.map((f) => ({
          file_id: f.file_id,
          filename: f.filename,
          content_type: f.content_type,
          size: f.size,
        })),
        {
          onOpen: () => console.debug('[chat SSE] open'),
          onMessage: ({ event, data }) => {
            console.debug('[chat SSE]', event, data)
            handleEvent({
              event: event as AgentSSEEvent['event'],
              data: data as AgentSSEEvent['data'],
            })
          },
          onClose: () => {
            console.debug('[chat SSE] close')
            if (chatHandleRef.current === handle) endChat()
          },
          onError: (e) => {
            console.error('[chat SSE] error', e)
            if (chatHandleRef.current === handle) endChat()
          },
        },
      )
      chatHandleRef.current = handle
    },
    [sessionId, handleEvent, endChat],
  )

  const handleEditUserMessage = useCallback(
    async (eventId: string, newMessage: string) => {
      if (!sessionId) return
      // Drop everything from the edited message onward locally so the panel
      // doesn't briefly show stale assistant output while the network call
      // truncates server-side.
      setMessages((prev) => reduceTruncateAtUserEvent(prev, eventId))
      lastEventId.current = ''
      lastNoMessageTool.current = undefined
      try {
        await agentApi.regenerateFromMessage(sessionId, eventId, newMessage)
      } catch (e) {
        console.error('Failed to regenerate:', e)
        showErrorToast('Failed to regenerate')
        return
      }
      chat(newMessage, [])
    },
    [sessionId, chat],
  )

  const restoreSession = useCallback(async () => {
    if (!sessionId) return
    try {
      // Bound the initial replay to the most recent N events. Long-running
      // sessions can accumulate thousands of events (8 MB+ payloads) which
      // dominates first-paint time. The chat panel still renders correctly
      // because virtualization + collapsible content keep visible work
      // bounded, and 300 events is enough to show recent context.
      const session = await agentApi.getSession(sessionId, { eventsLimit: 300 })
      setShareMode(session.is_shared ? 'public' : 'private')
      setRealTime(false)
      // Fetch full plan history (newest first) in parallel with event
      // replay. Without this, older plans don't surface because the
      // bounded event window may not include their PlanEvent.
      void agentApi
        .listSessionPlans(sessionId)
        .then((plans) => {
          if (plans.length === 0) return
          const mapped = plans.map((p) => ({
            plan_id: p.plan_id,
            title: p.title,
            goal: p.goal,
            status: p.status,
            error: p.error,
            commit_sha: p.commit_sha ?? null,
            tasks: p.tasks.map((t) => ({
              task_id: t.task_id,
              plan_id: t.plan_id,
              position: t.position,
              title: t.title,
              details: t.details,
              status: t.status,
              result: t.result,
              error: t.error,
              retries: t.retries,
              timestamp: 0,
            })) as TaskEventData[],
            timestamp: 0,
          })) as PlanEventData[]
          setPlanHistory(mapped)
          setPlan((cur) => cur ?? mapped[0])
        })
        .catch(() => {
          /* non-fatal */
        })
      // Synchronous ref so the for-loop's done/wait events don't tear
      // down the live chat connection. setState wouldn't apply until
      // next render.
      replayingRef.current = true
      try {
        for (const event of session.events) handleEvent(event)
      } finally {
        replayingRef.current = false
      }
      // handleTaskEvent skips setPlan during replay (render-storm guard
      // documented above). Without this fold, the plan panel would stay
      // pinned at whatever the initial PlanEvent EXECUTING captured —
      // typically all tasks PENDING — until the closing PlanEvent
      // COMPLETED overwrote the snapshot. Apply the latest task status
      // per task_id from the replayed events in a single setPlan call.
      const latestTaskByPlan = new Map<string, Map<string, TaskEventData>>()
      for (const event of session.events) {
        if (event.event !== 'task') continue
        const t = event.data as TaskEventData
        let m = latestTaskByPlan.get(t.plan_id)
        if (!m) {
          m = new Map()
          latestTaskByPlan.set(t.plan_id, m)
        }
        m.set(t.task_id, t)
      }
      if (latestTaskByPlan.size > 0) {
        const foldStatuses = (p: PlanEventData): PlanEventData => {
          const tasksForPlan = latestTaskByPlan.get(p.plan_id)
          if (!tasksForPlan) return p
          const tasks = p.tasks.map((t) => {
            const latest = tasksForPlan.get(t.task_id)
            return latest ? { ...t, ...latest } : t
          })
          return { ...p, tasks }
        }
        setPlan((prev) => (prev ? foldStatuses(prev) : prev))
        // PlanPanel renders from planHistory[viewedPlanIndex] first, so
        // applying the fold only to `plan` would leave the top summary
        // stale until a fresh PlanEvent overwrites planHistory.
        setPlanHistory((prev) =>
          prev.map((p) => (latestTaskByPlan.has(p.plan_id) ? foldStatuses(p) : p))
        )
      }
      setRealTime(true)
      // Surface the preview iframe by default — every session has one.
      toolPanelRef.current?.showToolPanel(
        {
          tool_call_id: `synthetic-preview-${sessionId}`,
          name: 'preview',
          function: '',
          args: {},
          status: 'called',
          timestamp: Date.now(),
        } as ToolContent,
        false,
      )
      if (
        session.status === SessionStatus.RUNNING ||
        session.status === SessionStatus.PENDING
      ) {
        chat()
      }
      void agentApi.clearUnreadMessageCount(sessionId).catch(() => {/* non-fatal */})
    } catch (e) {
      console.error('Failed to restore session:', e)
      showErrorToast('Session not found')
    }
  }, [sessionId, handleEvent, chat, toolPanelRef])

  // Reset on session change. StrictMode-safe: bail when re-fired for the
  // same session, otherwise the second mount would wipe the chatInFlight
  // guard and chat() would run twice. The pending-message handoff is a
  // take-once store, so it doesn't need a separate consumption guard.
  useEffect(() => {
    if (initializedSessionRef.current === sessionId) return
    initializedSessionRef.current = sessionId

    endChat()
    setMessages([])
    setPlan(undefined)
    setPlanHistory([])
    setViewedPlanIndex(0)
    setTitle('New Chat')
    setShareMode('private')
    setRealTime(true)
    setAwaitingReply(false)
    lastNoMessageTool.current = undefined
    lastEventId.current = undefined
    toolPanelRef.current?.hideToolPanel()
    onSessionChanged?.()

    const pending = sessionId ? usePendingMessage.getState().take(sessionId) : null
    if (pending) {
      chat(pending.message, pending.files)
    } else {
      void restoreSession()
    }

    // No cleanup `endChat()` on purpose. React 18 StrictMode runs
    // mount → unmount → mount in dev; a cleanup that cancels the SSE
    // handle would kill the fetch we JUST initiated, and the second
    // mount's `initializedSessionRef` guard would skip the re-init,
    // leaving the user's first message stranded (POST never reaches
    // the backend). Transitions between real sessionIds are handled
    // by the explicit `endChat()` at the top of this effect; on real
    // unmount the browser closes the EventSource automatically.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  return {
    messages,
    plan,
    planHistory,
    viewedPlanIndex,
    setViewedPlanIndex,
    title,
    isLoading,
    awaitingReply,
    setAwaitingReply,
    realTime,
    setRealTime,
    shareMode,
    setShareMode,
    lastNoMessageTool,
    chat,
    endChat,
    handleEditUserMessage,
    isLiveTool,
  }
}
