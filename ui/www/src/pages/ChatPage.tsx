import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useVirtualizer } from '@tanstack/react-virtual'
import { ArrowDown, FileSearch, PanelLeft, Settings2 } from 'lucide-react'

import * as agentApi from '@/api/agent'
import { isConsecutiveAssistant, type ToolContent } from '@/types/message'
import type { FileInfo } from '@/api/file'
import ChatBox from '@/components/ChatBox'
import ChatMessage from '@/components/ChatMessage'
import LoadingIndicator from '@/components/ui/LoadingIndicator'
import PlanPanel from '@/components/PlanPanel'
import PlanTimeline from '@/components/PlanTimeline'
import SessionSettingsDialog from '@/components/SessionSettingsDialog'
import ShareMenu from '@/components/ShareMenu'
import { SimpleBar, type SimpleBarHandle } from '@/components/ui/SimpleBar'
import ToolPanel, { type ToolPanelHandle } from '@/components/ToolPanel'
import type { InspectorPayload } from '@/components/toolViews/PreviewToolView'
import * as bus from '@/lib/eventBus'
import { useChatStream } from '@/hooks/useChatStream'
import { useFilePanel } from '@/hooks/useFilePanel'
import { useLeftPanel } from '@/hooks/useLeftPanel'
import { useSessionFileList } from '@/hooks/useSessionFileList'
import { showErrorToast } from '@/utils/toast'

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
  const { sessionId: routeSessionId } = useParams<{ sessionId: string }>()
  const isLeftPanelShow = useLeftPanel((s) => s.isLeftPanelShow)
  const toggleLeftPanel = useLeftPanel((s) => s.toggleLeftPanel)
  const showSessionFileList = useSessionFileList((s) => s.showSessionFileList)
  const hideFilePanel = useFilePanel((s) => s.hideFilePanel)

  const sessionId = routeSessionId

  // Page-local input/UI state. Everything chat-stream related (messages,
  // plan, isLoading, etc.) lives in useChatStream so the page stays focused
  // on layout and input handling.
  const [inputMessage, setInputMessage] = useState('')
  const [selectedContexts, setSelectedContexts] = useState<InspectorPayload[]>([])
  const [follow, setFollow] = useState(true)
  const [attachments, setAttachments] = useState<FileInfo[]>([])
  const [settingsOpen, setSettingsOpen] = useState(false)

  const toolPanel = useRef<ToolPanelHandle>(null)
  const simpleBarRef = useRef<SimpleBarHandle>(null)

  const stream = useChatStream({
    sessionId,
    toolPanelRef: toolPanel,
    onSessionChanged: () => {
      setInputMessage('')
      setAttachments([])
      setSelectedContexts([])
      setFollow(true)
      hideFilePanel()
    },
  })
  const {
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
    handleEditUserMessage,
    isLiveTool,
  } = stream


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
    return bus.on('helix:preview:select', (detail) => {
      if (!detail) return
      setSelectedContexts((prev) => {
        const key = inspectorContextKey(detail)
        if (prev.some((p) => inspectorContextKey(p) === key)) return prev
        return [...prev, detail]
      })
    })
  }, [])

  // ToolUse renders option buttons under any `message_ask_user` whose
  // args carry an `options` array. Click → option text dispatched here
  // → forwarded straight to chat() so the agent loop resumes with the
  // user's choice as the literal reply. We don't filter on
  // `awaitingReply`: a user clicking an option from history (e.g.
  // realizing later they wanted a different answer) gets to send it as
  // a fresh message — same semantics as typing it manually.
  useEffect(() => {
    return bus.on('helix:reply-with-option', (text) => {
      if (!text) return
      // Clear page-local input state too — the user might have typed
      // something they were about to send when they clicked an option.
      setInputMessage('')
      setAttachments([])
      setSelectedContexts([])
      setAwaitingReply(false)
      setFollow(true)
      chat(text, [])
    })
  }, [chat, setAwaitingReply])

  const handleScroll = () => {
    setFollow(simpleBarRef.current?.isScrolledToBottom() ?? false)
  }

  const handleFollow = () => {
    setFollow(true)
    simpleBarRef.current?.scrollToBottom()
  }

  const handleStop = () => {
    if (!sessionId) return
    agentApi.stopSession(sessionId).catch((e) => {
      console.error('Failed to stop session:', e)
      showErrorToast('Failed to stop session')
    })
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

  // Virtualize the message list so only items near the viewport are
  // mounted. Long sessions (3000+ events) previously rendered every
  // ChatMessage subtree at once — measurable seconds of mount + recurring
  // style-recalc on every state change. We hand the virtualizer
  // SimpleBar's scroll element so the existing scrollbar UX keeps working.
  const virtualParentRef = useRef<HTMLDivElement>(null)
  // The virtualizer's scrollMargin is the distance from the scroll element's
  // top to the start of the virtualized list (sticky header + PlanPanel).
  // useVirtualizer captures the option value at hook-init time, so reading
  // `virtualParentRef.current?.offsetTop` directly there always sees null on
  // the first render and the list ended up offset by ~the header's height.
  // Track it in state and let layout effects sync it once the DOM exists.
  const [virtualScrollMargin, setVirtualScrollMargin] = useState(0)
  useEffect(() => {
    const update = () => {
      const el = virtualParentRef.current
      if (!el) return
      setVirtualScrollMargin((cur) => (cur === el.offsetTop ? cur : el.offsetTop))
    }
    update()
    const ro = new ResizeObserver(update)
    if (virtualParentRef.current?.parentElement) {
      ro.observe(virtualParentRef.current.parentElement)
    }
    window.addEventListener('resize', update)
    return () => {
      ro.disconnect()
      window.removeEventListener('resize', update)
    }
  }, [])
  const virtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => simpleBarRef.current?.getScrollElement() ?? null,
    // Bumped from 120 to 200 — typical assistant bubble in this app is
    // 200-400px once rendered; 120 caused noticeable drift between
    // estimated and measured sizes during streaming, which manifested as
    // bottom-of-list shifting around as `measureElement` corrected.
    estimateSize: () => 200,
    scrollMargin: virtualScrollMargin,
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
  const scrollMargin = virtualScrollMargin

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
                <ShareMenu
                  sessionId={sessionId}
                  shareMode={shareMode}
                  onShareModeChange={setShareMode}
                />
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
                <PlanTimeline
                  plans={planHistory}
                  activeIndex={viewedPlanIndex}
                  onSelect={(idx) => setViewedPlanIndex(idx)}
                />
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
                const files = attachments
                setInputMessage('')
                setAttachments([])
                setSelectedContexts([])
                setAwaitingReply(false)
                setFollow(true)
                chat(merged, files)
              }}
              onStop={handleStop}
              placeholder={
                awaitingReply
                  ? "Reply to Helix's question..."
                  : 'Give Helix a task to work on...'
              }
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
      {sessionId && (
        <SessionSettingsDialog
          open={settingsOpen}
          onOpenChange={setSettingsOpen}
          sessionId={sessionId}
        />
      )}
    </SimpleBar>
  )
}
