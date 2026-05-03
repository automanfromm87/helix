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
import {
  type AttachmentsContent,
  type Message,
  type MessageContent,
  type TaskContent,
  type ToolContent,
} from '@/types/message'
import { SessionStatus } from '@/types/response'
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

const isPlaceholderEventId = (id?: string): boolean => !id || /^[0-]+$/.test(id)

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
  const lastTool = useRef<ToolContent | undefined>()
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
    setMessages((prev) => {
      // Streaming: incremental emissions of the same logical assistant turn
      // share `message_id`. Replace the existing bubble in place rather than
      // appending a new one. The final emit (partial=false) freezes the text.
      if (data.message_id) {
        const idx = prev.findIndex(
          (m) =>
            m.type === data.role &&
            (m.content as MessageContent).message_id === data.message_id,
        )
        if (idx >= 0) {
          const next = prev.slice()
          next[idx] = { type: data.role, content: { ...data } as MessageContent } as Message
          return next
        }
      }
      // The backend occasionally re-emits an event with the same event_id —
      // restoreSession replay overlapping with live SSE, multi-agent boundary
      // acks, etc. Treat same (type, event_id) as the same row to avoid
      // React duplicate-key warnings. Placeholder ids ("0...0", incl. nil-
      // UUID) are skipped so unrelated rows that share the sentinel don't
      // get collapsed into one.
      if (!isPlaceholderEventId(data.event_id)) {
        const idx = prev.findIndex(
          (m) =>
            m.type === data.role &&
            (m.content as MessageContent).event_id === data.event_id,
        )
        if (idx >= 0) {
          const next = prev.slice()
          next[idx] = { type: data.role, content: { ...data } as MessageContent } as Message
          return next
        }
      }
      const next: Message[] = [
        ...prev,
        { type: data.role, content: { ...data } as MessageContent } as Message,
      ]
      if (data.attachments && data.attachments.length > 0) {
        next.push({ type: 'attachments', content: { ...data } as AttachmentsContent })
      }
      return next
    })
  }, [])

  const handleToolEvent = useCallback((data: ToolEventData) => {
    const toolContent: ToolContent = { ...data }
    setMessages((prev) => {
      const directIdx = prev.findIndex(
        (m) =>
          m.type === 'tool' &&
          (m.content as ToolContent).tool_call_id === toolContent.tool_call_id,
      )
      if (directIdx >= 0) {
        const next = prev.slice()
        next[directIdx] = { type: 'tool', content: toolContent }
        return next
      }
      for (let i = prev.length - 1; i >= 0; i--) {
        const m = prev[i]
        if (m.type !== 'task') continue
        const task = m.content as TaskContent
        const toolIdx = task.tools.findIndex(
          (t) => t.tool_call_id === toolContent.tool_call_id,
        )
        if (toolIdx >= 0) {
          const nextTools = task.tools.slice()
          nextTools[toolIdx] = toolContent
          const next = prev.slice()
          next[i] = { type: 'task', content: { ...task, tools: nextTools } as TaskContent }
          return next
        }
        if (task.status === 'running') {
          const next = prev.slice()
          next[i] = {
            type: 'task',
            content: { ...task, tools: [...task.tools, toolContent] } as TaskContent,
          }
          return next
        }
        break
      }
      return [...prev, { type: 'tool', content: toolContent }]
    })
    lastTool.current = toolContent
    if (toolContent.name !== 'message') {
      lastNoMessageTool.current = toolContent
      if (realTimeRef.current) toolPanelRef.current?.showToolPanel(toolContent, true)
    }
  }, [toolPanelRef])

  const handleTaskEvent = useCallback((data: TaskEventData) => {
    setMessages((prev) => {
      const idx = prev.findIndex(
        (m) =>
          m.type === 'task' &&
          (m.content as TaskContent).task_id === data.task_id,
      )
      if (idx >= 0) {
        const existing = prev[idx].content as TaskContent
        const next = prev.slice()
        next[idx] = {
          type: 'task',
          content: {
            ...existing,
            status: data.status,
            title: data.title,
            details: data.details ?? existing.details,
            result: data.result ?? existing.result,
            error: data.error ?? existing.error,
          } as TaskContent,
        }
        return next
      }
      return [
        ...prev,
        {
          type: 'task',
          content: {
            task_id: data.task_id,
            plan_id: data.plan_id,
            position: data.position,
            title: data.title,
            details: data.details ?? null,
            status: data.status,
            result: data.result ?? null,
            error: data.error ?? null,
            tools: [],
            timestamp: data.timestamp,
          } as TaskContent,
        },
      ]
    })
    // Mirror task transitions into PlanPanel's snapshot — backend only
    // emits PlanEvent at plan-level transitions, so without this the plan
    // panel would show all tasks pending until the entire plan finished.
    // Skip during replay: a session restore already includes the plan
    // events that carry the canonical task statuses, and mirroring per-
    // task during replay stacks render pressure that has tripped React's
    // "Maximum update depth" guard on long sessions.
    if (replayingRef.current) return
    setPlan((prev) => {
      if (!prev || prev.plan_id !== data.plan_id) return prev
      const idx = prev.tasks.findIndex((t) => t.task_id === data.task_id)
      const merged: TaskEventData = {
        ...(idx >= 0 ? prev.tasks[idx] : ({} as TaskEventData)),
        ...data,
      }
      const tasks =
        idx >= 0
          ? prev.tasks.map((t, i) => (i === idx ? merged : t))
          : [...prev.tasks, merged].sort((a, b) => a.position - b.position)
      return { ...prev, tasks }
    })
  }, [])

  const handleErrorEvent = useCallback((data: ErrorEventData) => {
    setIsLoading(false)
    setMessages((prev) => [
      ...prev,
      {
        type: 'assistant',
        content: {
          event_id: data.event_id,
          content: `**⚠️ Error**\n\n${data.error}`,
          timestamp: data.timestamp,
        } as MessageContent,
      },
    ])
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

      if (message.trim()) {
        setMessages((prev) => [
          ...prev,
          {
            type: 'user',
            content: {
              content: message,
              timestamp: Math.floor(Date.now() / 1000),
            } as MessageContent,
          },
        ])
      }
      if (files.length > 0) {
        setMessages((prev) => [
          ...prev,
          {
            type: 'attachments',
            content: { role: 'user', attachments: files } as AttachmentsContent,
          },
        ])
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
      setMessages((prev) => {
        const idx = prev.findIndex(
          (m) => m.type === 'user' && (m.content as MessageContent).event_id === eventId,
        )
        return idx >= 0 ? prev.slice(0, idx) : prev
      })
      lastEventId.current = ''
      lastTool.current = undefined
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
    lastTool.current = undefined
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

    return () => {
      endChat()
    }
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
