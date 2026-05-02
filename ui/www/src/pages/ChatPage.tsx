import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { useVirtualizer } from '@tanstack/react-virtual'
import {
  ArrowDown,
  Check,
  FileSearch,
  Globe,
  Link as LinkIcon,
  Lock,
  PanelLeft,
  Settings2,
} from 'lucide-react'

import * as agentApi from '@/api/agent'
import {
  isConsecutiveAssistant,
  type AttachmentsContent,
  type Message,
  type MessageContent,
  type TaskContent,
  type ToolContent,
} from '@/types/message'
import {
  type AgentSSEEvent,
  type ErrorEventData,
  type MessageEventData,
  type PlanEventData,
  type TaskEventData,
  type TitleEventData,
  type ToolEventData,
} from '@/types/event'
import type { FileInfo } from '@/api/file'
import { SessionStatus } from '@/types/response'
import ChatBox from '@/components/ChatBox'
import ChatMessage from '@/components/ChatMessage'
import LoadingIndicator from '@/components/ui/LoadingIndicator'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/Popover'
import PlanPanel from '@/components/PlanPanel'
import SessionSettingsDialog from '@/components/SessionSettingsDialog'
import { ShareIcon } from '@/components/icons'
import { SimpleBar, type SimpleBarHandle } from '@/components/ui/SimpleBar'
import ToolPanel, { type ToolPanelHandle } from '@/components/ToolPanel'
import type { InspectorPayload } from '@/components/toolViews/PreviewToolView'
import { useFilePanel } from '@/hooks/useFilePanel'
import { useLeftPanel } from '@/hooks/useLeftPanel'
import { useSessionFileList } from '@/hooks/useSessionFileList'
import { copyToClipboard } from '@/utils/dom'
import { showErrorToast, showSuccessToast } from '@/utils/toast'
import { cn } from '@/lib/utils'

function inspectorContextBlock(p: InspectorPayload): string {
  const truncate = (s: string, max = 80) => (s.length > max ? `${s.slice(0, max)}…` : s)
  const path = p.source?.fileName.replace(/^.*\/project\//, '') ?? null
  const fileLine = path && p.source ? `${path}:${p.source.lineNumber}` : null
  const attrs = [p.id && `id="${p.id}"`, p.className && `class="${truncate(p.className)}"`]
    .filter(Boolean)
    .join(' ')
  const element = `<${p.tagName}${attrs ? ` ${attrs}` : ''}>`
  const lines = ['[Selected element]']
  if (p.componentName) lines.push(`component: <${p.componentName}>`)
  if (fileLine) lines.push(`file: ${fileLine}`)
  lines.push(`element: ${element}`)
  return lines.join('\n')
}

function inspectorContextKey(p: InspectorPayload): string {
  const src = p.source ? `${p.source.fileName}:${p.source.lineNumber}` : ''
  return `${p.componentName ?? ''}|${src}|${p.tagName}|${p.className}|${p.id}`
}

export default function ChatPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { sessionId: routeSessionId } = useParams<{ sessionId: string }>()
  const isLeftPanelShow = useLeftPanel((s) => s.isLeftPanelShow)
  const toggleLeftPanel = useLeftPanel((s) => s.toggleLeftPanel)
  const showSessionFileList = useSessionFileList((s) => s.showSessionFileList)
  const hideFilePanel = useFilePanel((s) => s.hideFilePanel)

  const [inputMessage, setInputMessage] = useState('')
  const [selectedContexts, setSelectedContexts] = useState<InspectorPayload[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [realTime, setRealTime] = useState(true)
  const [follow, setFollow] = useState(true)
  const [title, setTitle] = useState('New Chat')
  const [plan, setPlan] = useState<PlanEventData | undefined>(undefined)
  // History of all plans on this session, newest first. PlanPanel uses
  // this to let the user step back through prior plans (each user turn
  // typically creates a new Plan row — the current plan is just the
  // newest entry, but earlier turns' plans are valuable context.)
  const [planHistory, setPlanHistory] = useState<PlanEventData[]>([])
  // Index into planHistory the user is currently viewing. 0 = newest
  // (i.e. the live `plan`). When non-zero, PlanPanel shows the historical
  // snapshot and we DON'T overlay live SSE updates onto it.
  const [viewedPlanIndex, setViewedPlanIndex] = useState(0)
  const [attachments, setAttachments] = useState<FileInfo[]>([])
  const [shareMode, setShareMode] = useState<'private' | 'public'>('private')
  const [linkCopied, setLinkCopied] = useState(false)
  const [sharingLoading, setSharingLoading] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)

  const lastNoMessageTool = useRef<ToolContent | undefined>()
  const lastTool = useRef<ToolContent | undefined>()
  const lastEventId = useRef<string | undefined>()
  const cancelCurrentChat = useRef<(() => void) | null>(null)
  const toolPanel = useRef<ToolPanelHandle>(null)
  const initializedSessionRef = useRef<string | undefined>(undefined)
  // Sync flag tracking whether a chat() invocation is already in flight
  // for this session. Set the moment chat() starts, cleared when the SSE
  // stream's onClose / onError fires. The ref is checked at the top of
  // chat() so a second call (StrictMode remount, double-clicked Send,
  // SSE reconnect race) is dropped before any HTTP POST is issued.
  // Refs are stable across renders/remounts, so this works as a true
  // single-token mutex without depending on async state propagation.
  const chatInFlightRef = useRef(false)
  // Tracks whether the initial nav-state message has already been
  // consumed and kicked off chat(). React StrictMode double-mounts
  // every component in dev, and `location.state` survives that double-
  // mount unchanged — so without this guard, "build me a todo app"
  // arriving via /chat/<id> navigation would fire chat() twice and
  // create two parallel plans on the same session.
  const navMessageConsumedRef = useRef(false)
  const simpleBarRef = useRef<SimpleBarHandle>(null)
  // True only while restoreSession is synchronously replaying historical
  // events. Kept distinct from `realTime` (which also flips when the user
  // clicks a tool to view history) so terminal events from a live agent
  // still tear down the loading spinner correctly.
  const replayingRef = useRef(false)

  const sessionId = routeSessionId

  const isLastNoMessageTool = useCallback(
    (tool: ToolContent) => tool.tool_call_id === lastNoMessageTool.current?.tool_call_id,
    [],
  )

  const isLiveTool = useCallback(
    (tool: ToolContent) => {
      if (tool.status === 'calling') return true
      if (!isLastNoMessageTool(tool)) return false
      return tool.timestamp > Date.now() - 5 * 60 * 1000
    },
    [isLastNoMessageTool],
  )

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
          const next = [...prev]
          next[idx] = { type: data.role, content: { ...data } as MessageContent } as Message
          return next
        }
      }
      // The backend occasionally re-emits an event with the same event_id —
      // restoreSession replay overlapping with live SSE, multi-agent boundary
      // acks, etc. Treat same (type, event_id) as the same row to avoid
      // React duplicate-key warnings. event_id "00...000" placeholders are
      // skipped here so unrelated rows that share the sentinel don't get
      // collapsed into one.
      const isPlaceholderId = (id?: string) => !id || /^0+$/.test(id)
      if (!isPlaceholderId(data.event_id)) {
        const idx = prev.findIndex(
          (m) =>
            m.type === data.role &&
            (m.content as MessageContent).event_id === data.event_id,
        )
        if (idx >= 0) {
          const next = [...prev]
          next[idx] = { type: data.role, content: { ...data } as MessageContent } as Message
          return next
        }
      }
      const next = [
        ...prev,
        { type: data.role, content: { ...data } as MessageContent } as Message,
      ]
      if (data.attachments?.length > 0) {
        next.push({ type: 'attachments', content: { ...data } as AttachmentsContent })
      }
      return next
    })
  }, [])

  const handleToolEvent = useCallback(
    (data: ToolEventData) => {
      const toolContent: ToolContent = { ...data }

      setMessages((prev) => {
        const next = [...prev]
        const existing = lastTool.current
        if (existing && existing.tool_call_id === toolContent.tool_call_id) {
          // mutate the last tool reference in-place across the message tree.
          Object.assign(existing, toolContent)
          return next.slice()
        }
        // Tools belong to the most recent in-flight task (status=running).
        const lastTask = [...next].reverse().find((m) => m.type === 'task')?.content as
          | TaskContent
          | undefined
        if (lastTask && lastTask.status === 'running') {
          lastTask.tools.push(toolContent)
        } else {
          next.push({ type: 'tool', content: toolContent })
        }
        return next
      })
      lastTool.current = toolContent

      if (toolContent.name !== 'message') {
        lastNoMessageTool.current = toolContent
        if (realTime) toolPanel.current?.showToolPanel(toolContent, true)
      }
    },
    [realTime],
  )

  const handleTaskEvent = useCallback((data: TaskEventData) => {
    setMessages((prev) => {
      const next = [...prev]
      // Each task gets exactly one bubble in the chat — find it and update,
      // or insert if this is the first event for that task_id.
      const idx = next.findIndex(
        (m) =>
          m.type === 'task' &&
          (m.content as TaskContent).task_id === data.task_id,
      )
      if (idx >= 0) {
        const existing = next[idx].content as TaskContent
        Object.assign(existing, {
          status: data.status,
          title: data.title,
          details: data.details,
          result: data.result ?? existing.result,
          error: data.error ?? existing.error,
        })
        return next.slice()
      }
      next.push({
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
      })
      return next
    })
    // Mirror the per-task transition into the PlanPanel's snapshot. The
    // backend only emits PlanEvent at plan-level transitions (EXECUTING
    // start / COMPLETED / FAILED / replan), so without this the plan
    // panel would show all tasks pending until the entire plan finished.
    //
    // Skip during replay: a session restore replays every event in order,
    // which already includes the plan events that carry the canonical
    // task statuses. Mirroring per-task during replay does N redundant
    // setStates and stacks render pressure that has tripped React's
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
    // Surface errors as a clearly-marked assistant message so they don't blend
    // in with normal output.
    setMessages((prev) => [
      ...prev,
      {
        type: 'assistant',
        content: {
          content: `**⚠️ Error**\n\n${data.error}`,
          timestamp: data.timestamp,
        } as MessageContent,
      },
    ])
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
          // Maintain the history list: replace if same plan_id (live
          // updates to the active plan), prepend if new (a follow-up
          // turn just produced a fresh plan).
          setPlanHistory((prev) => {
            const idx = prev.findIndex((p) => p.plan_id === planData.plan_id)
            if (idx >= 0) {
              const next = [...prev]
              next[idx] = planData
              return next
            }
            return [planData, ...prev]
          })
          // Snap viewer back to newest whenever a fresh plan arrives so
          // the user sees the new live plan instead of being stuck on
          // an older snapshot from the previous turn.
          setViewedPlanIndex(0)
          break
        }
        case 'done':
        case 'wait':
          // Explicit terminal events — sse-starlette keeps the SSE open with
          // keep-alive pings, so onClose isn't reliable. Skip during replay
          // so an old `done` event in session history doesn't cancel the
          // brand-new chat() SSE that just started.
          if (!replayingRef.current) {
            setIsLoading(false)
            cancelCurrentChat.current?.()
            cancelCurrentChat.current = null
            chatInFlightRef.current = false
          }
          break
        default:
          break
      }
      lastEventId.current = event.data.event_id
    },
    [handleMessageEvent, handleToolEvent, handleTaskEvent, handleErrorEvent],
  )

  const chat = useCallback(
    async (message = '', files: FileInfo[] = []) => {
      if (!sessionId) return
      // Synchronous in-flight guard. The check + set must happen before
      // any await — otherwise two near-simultaneous callers (StrictMode
      // remount, double-clicked Send button) both pass the check and
      // both fire the HTTP POST, creating two parallel Plans on the
      // server. The flag is cleared in onClose / onError / catch.
      if (chatInFlightRef.current) {
        console.debug('[chat] dropped duplicate invocation while in flight')
        return
      }
      chatInFlightRef.current = true
      cancelCurrentChat.current?.()
      cancelCurrentChat.current = null

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

      setFollow(true)
      setInputMessage('')
      setAttachments([])
      setSelectedContexts([])
      setIsLoading(true)

      try {
        const cancel = await agentApi.chatWithSession(
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
            onOpen: () => {
              console.debug('[chat SSE] open')
              setIsLoading(true)
            },
            onMessage: ({ event, data }) => {
              console.debug('[chat SSE]', event, data)
              handleEvent({
                event: event as AgentSSEEvent['event'],
                data: data as AgentSSEEvent['data'],
              })
            },
            onClose: () => {
              console.debug('[chat SSE] close')
              setIsLoading(false)
              cancelCurrentChat.current = null
              chatInFlightRef.current = false
            },
            onError: (e) => {
              console.error('[chat SSE] error', e)
              setIsLoading(false)
              cancelCurrentChat.current = null
              chatInFlightRef.current = false
            },
          },
        )
        cancelCurrentChat.current = cancel
      } catch (e) {
        console.error('Chat error:', e)
        setIsLoading(false)
        cancelCurrentChat.current = null
        chatInFlightRef.current = false
      }
    },
    [sessionId, handleEvent],
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
      void chat(newMessage, [])
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
      // bounded, and 300 events is enough to show the user the recent
      // context. Older history can be added via a future scroll-up loader.
      const session = await agentApi.getSession(sessionId, { eventsLimit: 300 })
      setShareMode(session.is_shared ? 'public' : 'private')
      setRealTime(false)
      // Fetch the full plan history (newest first) in parallel with the
      // event replay. Without this, older plans don't surface because
      // the bounded event window may not include their PlanEvent.
      void agentApi.listSessionPlans(sessionId).then((plans) => {
        if (plans.length === 0) return
        // PlanItem from the API maps cleanly onto our PlanEventData
        // shape (same keys; statuses share the literal union).
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
        // If event replay hasn't already pinned a plan, default to the
        // newest one so PlanPanel renders something on session restore.
        setPlan((cur) => cur ?? mapped[0])
      }).catch(() => {/* non-fatal */})
      // Synchronous ref so the for-loop's done/wait events don't tear down
      // the live chat connection. setState wouldn't apply until next render.
      replayingRef.current = true
      try {
        for (const event of session.events) handleEvent(event)
      } finally {
        replayingRef.current = false
      }
      setRealTime(true)
      // Surface the preview iframe by default — every session has one
      // (sandbox port mapping is reserved at create time), and the user
      // wants to see the running app first, not whatever the agent's
      // last tool call was. Agent tool events later in the session will
      // replace this with their own content; the Preview tab stays
      // available in the dropdown.
      toolPanel.current?.showToolPanel(
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
        await chat()
      }
      void agentApi.clearUnreadMessageCount(sessionId)
    } catch (e) {
      console.error('Failed to restore session:', e)
      showErrorToast('Session not found')
    }
  }, [sessionId, handleEvent, chat])

  // Reset on session change. StrictMode-safe: bail when re-fired for the
  // same session, otherwise the second mount would wipe the chatInFlight
  // / navMessageConsumed guards and chat() would run twice.
  useEffect(() => {
    if (initializedSessionRef.current === sessionId) return
    initializedSessionRef.current = sessionId

    cancelCurrentChat.current?.()
    cancelCurrentChat.current = null
    // Clear in-flight + nav-consumption flags so the new session starts
    // with a clean slate. Without this, navigating from one chat to
    // another could leave the in-flight flag stuck if the prior SSE
    // hadn't closed cleanly.
    chatInFlightRef.current = false
    navMessageConsumedRef.current = false
    setMessages([])
    setPlan(undefined)
    setPlanHistory([])
    setViewedPlanIndex(0)
    setTitle('New Chat')
    setAttachments([])
    setSelectedContexts([])
    setShareMode('private')
    setLinkCopied(false)
    setRealTime(true)
    setFollow(true)
    lastTool.current = undefined
    lastNoMessageTool.current = undefined
    lastEventId.current = undefined
    toolPanel.current?.hideToolPanel()
    hideFilePanel()

    const navState = (location.state as { message?: string; files?: FileInfo[] } | null) ?? null
    if (navState?.message && !navMessageConsumedRef.current) {
      // StrictMode-safe: claim the consumption synchronously so the
      // remount can't re-fire. window.history.replaceState alone isn't
      // enough — React's location.state closure survives the cleanup.
      navMessageConsumedRef.current = true
      window.history.replaceState({}, document.title)
      void chat(navState.message, navState.files ?? [])
    } else if (!navState?.message) {
      void restoreSession()
    }

    return () => {
      cancelCurrentChat.current?.()
      cancelCurrentChat.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  // Auto-scroll on new message when in follow mode.
  //
  // Streaming chat fires `setMessages` many times per second, and a naive
  // `scrollToBottom` per render produces jittery, visibly-rebounding scroll
  // on long answers (the scrollbar tries to catch up with each chunk).
  // Coalesce via rAF: schedule one pending scroll per frame at most, drop
  // any that arrive while a frame is already queued.
  const pendingScrollFrame = useRef<number | null>(null)
  useEffect(() => {
    if (!follow) return
    if (pendingScrollFrame.current !== null) return
    pendingScrollFrame.current = requestAnimationFrame(() => {
      pendingScrollFrame.current = null
      simpleBarRef.current?.scrollToBottom()
    })
    return () => {
      if (pendingScrollFrame.current !== null) {
        cancelAnimationFrame(pendingScrollFrame.current)
        pendingScrollFrame.current = null
      }
    }
  }, [messages, follow])

  // PreviewToolView dispatches `helix:preview:select` when the user
  // clicks an element in iframe inspect mode. We collect these as chips
  // above the chat input; on send, the formatted blocks are prepended to
  // the message so the agent gets the React source context.
  useEffect(() => {
    const onSelect = (e: Event) => {
      const detail = (e as CustomEvent<InspectorPayload>).detail
      if (!detail) return
      setSelectedContexts((prev) => {
        const key = inspectorContextKey(detail)
        if (prev.some((p) => inspectorContextKey(p) === key)) return prev
        return [...prev, detail]
      })
    }
    window.addEventListener('helix:preview:select', onSelect)
    return () => window.removeEventListener('helix:preview:select', onSelect)
  }, [])

  const handleScroll = () => {
    setFollow(simpleBarRef.current?.isScrolledToBottom() ?? false)
  }

  const handleFollow = () => {
    setFollow(true)
    simpleBarRef.current?.scrollToBottom()
  }

  const handleStop = () => {
    if (sessionId) void agentApi.stopSession(sessionId)
  }

  const handleToolClick = (tool: ToolContent) => {
    setRealTime(false)
    if (sessionId) toolPanel.current?.showToolPanel(tool, isLiveTool(tool))
  }

  const jumpToRealTime = () => {
    setRealTime(true)
    if (lastNoMessageTool.current) {
      toolPanel.current?.showToolPanel(
        lastNoMessageTool.current,
        isLiveTool(lastNoMessageTool.current),
      )
    }
  }

  const handleShareModeChange = async (mode: 'private' | 'public') => {
    if (!sessionId || sharingLoading) return
    if (shareMode === mode) {
      setLinkCopied(false)
      return
    }
    try {
      setSharingLoading(true)
      if (mode === 'public') await agentApi.shareSession(sessionId)
      else await agentApi.unshareSession(sessionId)
      setShareMode(mode)
      setLinkCopied(false)
    } catch (e) {
      console.error('Error changing share mode:', e)
      showErrorToast('Failed to change sharing settings')
    } finally {
      setSharingLoading(false)
    }
  }

  const handleInstantShare = async () => {
    if (!sessionId) return
    setSharingLoading(true)
    try {
      await agentApi.shareSession(sessionId)
      setShareMode('public')
      setLinkCopied(false)
    } catch (e) {
      console.error('Error sharing session:', e)
      showErrorToast('Failed to share session')
    } finally {
      setSharingLoading(false)
    }
  }

  const handleCopyLink = async () => {
    if (!sessionId) return
    const shareUrl = `${window.location.origin}/share/${sessionId}`
    const ok = await copyToClipboard(shareUrl)
    if (ok) {
      setLinkCopied(true)
      window.setTimeout(() => setLinkCopied(false), 3000)
      showSuccessToast('Link copied to clipboard')
    } else {
      showErrorToast('Failed to copy link')
    }
  }

  // Virtualize the message list so only items near the viewport are
  // mounted. Long sessions (3000+ events) previously rendered every
  // ChatMessage subtree at once — measurable seconds of mount + recurring
  // style-recalc on every state change. We hand the virtualizer
  // SimpleBar's scroll element so the existing scrollbar UX keeps working.
  const virtualParentRef = useRef<HTMLDivElement>(null)
  const virtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => simpleBarRef.current?.getScrollElement() ?? null,
    // Bumped from 120 to 200 — typical assistant bubble in this app is
    // 200-400px once rendered; 120 caused noticeable drift between
    // estimated and measured sizes during streaming, which manifested as
    // bottom-of-list shifting around as `measureElement` corrected.
    estimateSize: () => 200,
    // Account for sticky header / plan panel / inner padding above the
    // virtualized list — items position relative to scrollMargin so the
    // first item lines up correctly under the sticky region.
    scrollMargin: virtualParentRef.current?.offsetTop ?? 0,
    overscan: 8,
    // Re-key when the underlying message identity changes (e.g. edit-and-
    // regenerate truncates the array), so cached row measurements don't
    // mis-align with the new content.
    getItemKey: (index) => {
      const m = messages[index]
      const c = m?.content as { event_id?: string; tool_call_id?: string; task_id?: string }
      // The chat list is append-only; truncation (edit-and-regenerate)
      // shifts subsequent indices, which is the *desired* re-key signal so
      // virtualizer measurements don't carry over to a different message.
      // Including the index makes the key globally unique even when the
      // backend re-emits an event_id (replay / multi-agent boundary acks),
      // while the natural id keeps the key stable for streaming updates
      // that replace a row in place at the same index.
      const id = c?.event_id ?? c?.tool_call_id ?? c?.task_id ?? 'x'
      return `${m?.type ?? 'm'}:${id}:${index}`
    },
  })

  const virtualItems = virtualizer.getVirtualItems()
  const totalHeight = virtualizer.getTotalSize()
  const scrollMargin = virtualizer.options.scrollMargin ?? 0

  return (
    <SimpleBar ref={simpleBarRef} onScroll={handleScroll}>
      <div className="relative flex flex-col h-full flex-1 min-w-0 px-5">
        <div className="sm:min-w-[390px] flex flex-row items-center justify-between pt-3 pb-1 gap-1 sticky top-0 z-10 bg-[var(--background-gray-main)] flex-shrink-0">
          <div className="flex items-center flex-1">
            <div className="relative flex items-center">
              {!isLeftPanelShow && (
                <div
                  onClick={toggleLeftPanel}
                  className="flex h-7 w-7 items-center justify-center cursor-pointer rounded-md hover:bg-[var(--fill-tsp-gray-main)]"
                >
                  <PanelLeft className="size-5 text-[var(--icon-secondary)]" />
                </div>
              )}
            </div>
          </div>
          <div className="max-w-full sm:max-w-[768px] sm:min-w-[390px] flex w-full flex-col gap-[4px] overflow-hidden">
            <div className="text-[var(--text-primary)] text-lg font-medium w-full flex flex-row items-center justify-between flex-1 min-w-0 gap-2">
              <div className="flex flex-row items-center gap-[6px] flex-1 min-w-0">
                <span className="whitespace-nowrap text-ellipsis overflow-hidden">{title}</span>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <Popover>
                  <PopoverTrigger asChild>
                    <button className="h-8 px-3 rounded-[100px] inline-flex items-center gap-1 cursor-pointer outline outline-1 outline-offset-[-1px] outline-[var(--border-btn-main)] hover:bg-[var(--fill-tsp-white-light)] me-1.5">
                      <ShareIcon color="var(--icon-secondary)" />
                      <span className="text-[var(--text-secondary)] text-sm font-medium">Share</span>
                    </button>
                  </PopoverTrigger>
                  <PopoverContent>
                    <div
                      className="w-[400px] flex flex-col rounded-2xl bg-[var(--background-menu-white)] shadow-[0px_8px_32px_0px_var(--shadow-S),0px_0px_0px_1px_var(--border-light)]"
                      style={{ maxWidth: 'calc(-16px + 100vw)' }}
                    >
                      <div className="flex flex-col pt-[12px] px-[16px] pb-[16px]">
                        <div
                          onClick={() => handleShareModeChange('private')}
                          className={cn(
                            'flex items-center gap-[10px] px-[8px] -mx-[8px] py-[8px] rounded-[8px] cursor-pointer hover:bg-[var(--fill-tsp-white-main)]',
                            sharingLoading && 'pointer-events-none opacity-50',
                          )}
                        >
                          <div
                            className={cn(
                              'w-[32px] h-[32px] rounded-[8px] flex items-center justify-center',
                              shareMode === 'private'
                                ? 'bg-[var(--Button-primary-black)]'
                                : 'bg-[var(--fill-tsp-white-dark)]',
                            )}
                          >
                            <Lock
                              size={16}
                              stroke={
                                shareMode === 'private'
                                  ? 'var(--text-onblack)'
                                  : 'var(--icon-primary)'
                              }
                              strokeWidth={2}
                            />
                          </div>
                          <div className="flex flex-col flex-1 min-w-0">
                            <div className="text-sm font-medium text-[var(--text-primary)]">
                              Private Only
                            </div>
                            <div className="text-[13px] text-[var(--text-tertiary)]">
                              Only visible to you
                            </div>
                          </div>
                          <Check
                            size={20}
                            className={cn(
                              shareMode === 'private' ? 'ml-auto' : 'ml-auto invisible',
                            )}
                            color={
                              shareMode === 'private'
                                ? 'var(--icon-primary)'
                                : 'var(--icon-tertiary)'
                            }
                          />
                        </div>
                        <div
                          onClick={() => handleShareModeChange('public')}
                          className={cn(
                            'flex items-center gap-[10px] px-[8px] -mx-[8px] py-[8px] rounded-[8px] cursor-pointer hover:bg-[var(--fill-tsp-white-main)]',
                            sharingLoading && 'pointer-events-none opacity-50',
                          )}
                        >
                          <div
                            className={cn(
                              'w-[32px] h-[32px] rounded-[8px] flex items-center justify-center',
                              shareMode === 'public'
                                ? 'bg-[var(--Button-primary-black)]'
                                : 'bg-[var(--fill-tsp-white-dark)]',
                            )}
                          >
                            <Globe
                              size={16}
                              stroke={
                                shareMode === 'public'
                                  ? 'var(--text-onblack)'
                                  : 'var(--icon-primary)'
                              }
                              strokeWidth={2}
                            />
                          </div>
                          <div className="flex flex-col flex-1 min-w-0">
                            <div className="text-sm font-medium text-[var(--text-primary)]">
                              Public Access
                            </div>
                            <div className="text-[13px] text-[var(--text-tertiary)]">
                              Anyone with the link can view
                            </div>
                          </div>
                          <Check
                            size={20}
                            className={cn(
                              shareMode === 'public' ? 'ml-auto' : 'ml-auto invisible',
                            )}
                            color={
                              shareMode === 'public'
                                ? 'var(--icon-primary)'
                                : 'var(--icon-tertiary)'
                            }
                          />
                        </div>
                        <div className="border-t border-[var(--border-main)] mt-[4px]" />
                        {shareMode === 'private' ? (
                          <button
                            onClick={(e) => {
                              e.stopPropagation()
                              void handleInstantShare()
                            }}
                            disabled={sharingLoading}
                            className="inline-flex items-center justify-center whitespace-nowrap font-medium transition-colors hover:opacity-90 bg-[var(--Button-primary-black)] text-[var(--text-onblack)] h-[36px] px-[12px] rounded-[10px] gap-[6px] text-sm w-full mt-[16px] disabled:opacity-50"
                          >
                            {sharingLoading ? (
                              <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                            ) : (
                              <LinkIcon size={16} stroke="currentColor" strokeWidth={2} />
                            )}
                            {sharingLoading ? 'Sharing...' : 'Share Instantly'}
                          </button>
                        ) : (
                          <button
                            onClick={(e) => {
                              e.stopPropagation()
                              void handleCopyLink()
                            }}
                            className={cn(
                              'inline-flex items-center justify-center whitespace-nowrap font-medium transition-colors h-[36px] px-[12px] rounded-[10px] gap-[6px] text-sm w-full mt-[16px]',
                              linkCopied
                                ? 'bg-[var(--Button-primary-white)] text-[var(--text-primary)] hover:opacity-70 border border-[var(--border-btn-main)]'
                                : 'bg-[var(--Button-primary-black)] text-[var(--text-onblack)] hover:opacity-90',
                            )}
                          >
                            {linkCopied ? (
                              <Check size={16} color="var(--text-primary)" />
                            ) : (
                              <LinkIcon size={16} stroke="currentColor" strokeWidth={2} />
                            )}
                            {linkCopied ? 'Link Copied' : 'Copy Link'}
                          </button>
                        )}
                      </div>
                    </div>
                  </PopoverContent>
                </Popover>
                <button
                  onClick={() => setSettingsOpen(true)}
                  title="Session settings"
                  className="p-[5px] flex items-center justify-center hover:bg-[var(--fill-tsp-white-dark)] rounded-lg cursor-pointer"
                >
                  <Settings2 className="text-[var(--icon-secondary)]" size={18} />
                </button>
                <button
                  onClick={() => showSessionFileList()}
                  className="p-[5px] flex items-center justify-center hover:bg-[var(--fill-tsp-white-dark)] rounded-lg cursor-pointer"
                >
                  <FileSearch className="text-[var(--icon-secondary)]" size={18} />
                </button>
              </div>
            </div>
          </div>
          <div className="flex-1" />
        </div>

        <div className="mx-auto w-full max-w-full sm:max-w-[768px] sm:min-w-[390px] flex flex-col flex-1">
          {(() => {
            // Pick which plan to render: the user's history selection
            // (when they've stepped back) or the live `plan`. Falls back
            // through both so the panel survives partial state during
            // session restore.
            const displayedPlan =
              planHistory[viewedPlanIndex] ?? plan ?? planHistory[0]
            if (!displayedPlan || displayedPlan.tasks.length === 0) return null
            return (
              <div className="sticky top-0 z-10 pt-2 pb-1 bg-[var(--background-gray-main)]">
                <PlanPanel
                  plan={displayedPlan}
                  historyTotal={planHistory.length}
                  historyIndex={viewedPlanIndex}
                  onHistoryNav={(delta) => {
                    setViewedPlanIndex((cur) => {
                      const next = cur + delta
                      if (next < 0 || next >= planHistory.length) return cur
                      return next
                    })
                  }}
                />
              </div>
            )
          })()}
          <div
            ref={virtualParentRef}
            className="w-full pt-[12px] pb-[80px] flex-1"
            style={{ position: 'relative', minHeight: totalHeight }}
          >
            {virtualItems.map((virtualRow) => {
              const message = messages[virtualRow.index]
              if (!message) return null
              return (
                <div
                  key={virtualRow.key}
                  data-index={virtualRow.index}
                  ref={virtualizer.measureElement}
                  // The wrapper is absolutely positioned by the virtualizer.
                  // `chat-message-row` keeps the off-screen content-visibility
                  // optimization for double-defense — only on-screen virtual
                  // items hit the DOM, and even those skip paint when the
                  // user scrolls them out before unmount.
                  className="chat-message-row"
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    transform: `translateY(${virtualRow.start - scrollMargin}px)`,
                    paddingBottom: 12,
                  }}
                >
                  <ChatMessage
                    message={message}
                    hideHeader={isConsecutiveAssistant(messages, virtualRow.index)}
                    onToolClick={handleToolClick}
                    onEditUserMessage={handleEditUserMessage}
                  />
                </div>
              )
            })}
            {isLoading && (
              <div
                style={{
                  position: 'absolute',
                  top: totalHeight,
                  left: 0,
                  width: '100%',
                }}
              >
                <LoadingIndicator text="Thinking" />
              </div>
            )}
          </div>

          <div className="flex flex-col bg-[var(--background-gray-main)] sticky bottom-0">
            {!follow && (
              <button
                onClick={handleFollow}
                className="flex items-center justify-center w-9 h-9 rounded-full bg-[var(--background-white-main)] hover:bg-[var(--background-gray-main)] cursor-pointer border border-[var(--border-main)] shadow-[0px_5px_16px_0px_var(--shadow-S)] absolute -top-20 left-1/2 -translate-x-1/2"
              >
                <ArrowDown className="text-[var(--icon-primary)]" size={20} />
              </button>
            )}
            <ChatBox
              rows={1}
              value={inputMessage}
              onChange={setInputMessage}
              isRunning={isLoading}
              attachments={attachments}
              onAttachmentsChange={setAttachments}
              contexts={selectedContexts.map((c) => ({
                id: inspectorContextKey(c),
                label: c.componentName ?? `<${c.tagName}>`,
                detail: c.source
                  ? `${c.source.fileName.replace(/^.*\/project\//, '')}:${c.source.lineNumber}`
                  : undefined,
              }))}
              onRemoveContext={(id) =>
                setSelectedContexts((prev) =>
                  prev.filter((p) => inspectorContextKey(p) !== id),
                )
              }
              onSubmit={() => {
                const ctx = selectedContexts.map(inspectorContextBlock).join('\n\n')
                const merged = ctx ? `${ctx}\n\n${inputMessage}`.trim() : inputMessage
                void chat(merged, attachments)
              }}
              onStop={handleStop}
            />
          </div>
        </div>
      </div>
      <ToolPanel
        ref={toolPanel}
        sessionId={sessionId}
        realTime={realTime}
        isShare={false}
        onJumpToRealTime={jumpToRealTime}
      />
      <SessionSettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        sessionId={sessionId}
      />
    </SimpleBar>
  )
}
