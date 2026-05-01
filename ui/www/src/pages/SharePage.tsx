import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { ArrowDown, Bot, FileSearch, Link as LinkIcon, Play } from 'lucide-react'

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
import ChatMessage from '@/components/ChatMessage'
import LoadingIndicator from '@/components/ui/LoadingIndicator'
import PlanPanel from '@/components/PlanPanel'
import { HelixLogoTextIcon } from '@/components/icons'
import { SimpleBar, type SimpleBarHandle } from '@/components/ui/SimpleBar'
import ToolPanel, { type ToolPanelHandle } from '@/components/ToolPanel'
import { useFilePanel } from '@/hooks/useFilePanel'
import { useSessionFileList } from '@/hooks/useSessionFileList'
import { copyToClipboard } from '@/utils/dom'
import { showErrorToast, showSuccessToast } from '@/utils/toast'

export default function SharePage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const showSessionFileList = useSessionFileList((s) => s.showSessionFileList)
  const hideFilePanel = useFilePanel((s) => s.hideFilePanel)

  const [isLoading, setIsLoading] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [realTime, setRealTime] = useState(true)
  const [follow, setFollow] = useState(true)
  const [title, setTitle] = useState('New Chat')
  const [plan, setPlan] = useState<PlanEventData | undefined>(undefined)
  const [showReplayOverlay, setShowReplayOverlay] = useState(false)
  const [countdown, setCountdown] = useState(3)
  const [replayCompleted, setReplayCompleted] = useState(false)

  const lastNoMessageTool = useRef<ToolContent | undefined>()
  const lastTool = useRef<ToolContent | undefined>()
  const lastEventId = useRef<string | undefined>()
  const jumpToEnd = useRef(false)
  const countdownTimer = useRef<number | null>(null)
  const toolPanel = useRef<ToolPanelHandle>(null)
  const simpleBarRef = useRef<SimpleBarHandle>(null)

  const handleMessageEvent = useCallback((data: MessageEventData) => {
    setMessages((prev) => {
      // Streaming: replace prior partial with the same message_id in place.
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
          Object.assign(existing, toolContent)
          return next.slice()
        }
        const lastStep = [...next].reverse().find((m) => m.type === 'task')?.content as
          | TaskContent
          | undefined
        if (lastStep && lastStep.status === 'running') lastStep.tools.push(toolContent)
        else next.push({ type: 'tool', content: toolContent })
        return next
      })
      lastTool.current = toolContent
      if (toolContent.name !== 'message') {
        lastNoMessageTool.current = toolContent
        if (realTime) toolPanel.current?.showToolPanel(toolContent, false)
      }
    },
    [realTime],
  )

  const handleStepEvent = useCallback((data: TaskEventData) => {
    setMessages((prev) => {
      const next = [...prev]
      const lastStep = [...next].reverse().find((m) => m.type === 'task')?.content as
        | TaskContent
        | undefined
      if (data.status === 'running') {
        next.push({ type: 'task', content: { ...data, tools: [] } as TaskContent })
      } else if (data.status === 'completed' && lastStep) {
        lastStep.status = 'completed'
      } else if (data.status === 'failed') {
        setIsLoading(false)
      }
      return next
    })
  }, [])

  const handleErrorEvent = useCallback((data: ErrorEventData) => {
    setIsLoading(false)
    setMessages((prev) => [
      ...prev,
      {
        type: 'assistant',
        content: { content: data.error, timestamp: data.timestamp } as MessageContent,
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
          handleStepEvent(event.data as TaskEventData)
          break
        case 'error':
          handleErrorEvent(event.data as ErrorEventData)
          break
        case 'title':
          setTitle((event.data as TitleEventData).title)
          break
        case 'plan':
          setPlan(event.data as PlanEventData)
          break
        default:
          break
      }
      lastEventId.current = event.data.event_id
    },
    [handleMessageEvent, handleToolEvent, handleStepEvent, handleErrorEvent],
  )

  const restoreSession = useCallback(async () => {
    if (!sessionId) return
    try {
      const session = await agentApi.getSharedSession(sessionId)
      setRealTime(false)
      setFollow(false)
      for (const event of session.events) handleEvent(event)
      setRealTime(true)
    } catch (e) {
      console.error('Failed to restore session:', e)
      showErrorToast('Session not found')
    }
  }, [sessionId, handleEvent])

  const replay = useCallback(async () => {
    if (!sessionId) return
    hideFilePanel()
    toolPanel.current?.hideToolPanel()
    setMessages([])
    setPlan(undefined)
    setTitle('New Chat')
    lastTool.current = undefined
    lastNoMessageTool.current = undefined
    lastEventId.current = undefined
    setReplayCompleted(false)
    try {
      const session = await agentApi.getSharedSession(sessionId)
      setRealTime(true)
      setIsLoading(true)
      for (const event of session.events) {
        if (!jumpToEnd.current) await new Promise((r) => setTimeout(r, 300))
        handleEvent(event)
      }
      setIsLoading(false)
      setReplayCompleted(true)
    } catch (e) {
      console.error('Replay failed:', e)
      setIsLoading(false)
    }
  }, [sessionId, handleEvent, hideFilePanel])

  const startCountdown = useCallback(() => {
    if (countdownTimer.current) window.clearInterval(countdownTimer.current)
    setCountdown(3)
    countdownTimer.current = window.setInterval(() => {
      setCountdown((c) => {
        if (c <= 1) {
          if (countdownTimer.current) window.clearInterval(countdownTimer.current)
          countdownTimer.current = null
          setShowReplayOverlay(false)
          void replay()
        }
        return c - 1
      })
    }, 1000)
  }, [replay])

  const startReplay = () => {
    if (countdownTimer.current) {
      window.clearInterval(countdownTimer.current)
      countdownTimer.current = null
    }
    setShowReplayOverlay(false)
    void replay()
  }

  useEffect(() => {
    hideFilePanel()
    if (sessionId) {
      void restoreSession()
      setShowReplayOverlay(true)
      startCountdown()
    }
    return () => {
      if (countdownTimer.current) {
        window.clearInterval(countdownTimer.current)
        countdownTimer.current = null
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  useEffect(() => {
    if (follow) requestAnimationFrame(() => simpleBarRef.current?.scrollToBottom())
  }, [messages, follow])

  const handleScroll = () => {
    setFollow(simpleBarRef.current?.isScrolledToBottom() ?? false)
  }

  const handleFollow = () => {
    setFollow(true)
    simpleBarRef.current?.scrollToBottom()
  }

  const handleToolClick = (tool: ToolContent) => {
    setRealTime(false)
    if (sessionId) toolPanel.current?.showToolPanel(tool, false)
  }

  const jumpToRealTime = () => {
    setRealTime(true)
    if (lastNoMessageTool.current) {
      toolPanel.current?.showToolPanel(lastNoMessageTool.current, false)
    }
  }

  const handleCopyLink = async () => {
    if (!sessionId) return
    const shareUrl = `${window.location.origin}/share/${sessionId}`
    const ok = await copyToClipboard(shareUrl)
    if (ok) showSuccessToast('Link copied to clipboard')
    else showErrorToast('Failed to copy link')
  }

  const renderedMessages = useMemo(
    () =>
      messages.map((message, index) => (
        <ChatMessage
          key={index}
          message={message}
          hideHeader={isConsecutiveAssistant(messages, index)}
          onToolClick={handleToolClick}
        />
      )),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [messages],
  )

  return (
    <SimpleBar ref={simpleBarRef} onScroll={handleScroll}>
      <div className="relative flex flex-col h-full flex-1 min-w-0 px-5">
        <header className="sm:h-auto sticky top-0 left-0 right-0 z-10">
          <div className="min-h-[52px] px-[16px] py-[10px] sm:px-5 sm:py-3 items-center flex justify-between bg-[var(--background-gray-main)]">
            <div className="flex items-center gap-2 sm:gap-3 flex-1 min-w-0 sm:flex-none">
              <a href="/" className="hidden sm:flex">
                <div className="flex items-center gap-[3px]">
                  <Bot size={24} className="w-6 h-6" />
                  <HelixLogoTextIcon height={30} width={65} />
                </div>
              </a>
              <div className="text-[var(--text-primary)] text-lg font-[600] leading-[24px] flex-1 min-w-0 text-left sm:hidden truncate">
                {title}
              </div>
            </div>
            <div className="text-lg font-medium text-[var(--text-primary)] flex-1 min-w-0 text-center hidden sm:block truncate">
              {title}
            </div>
            <div className="flex items-center sm:gap-3">
              <button
                onClick={handleCopyLink}
                className="p-2 flex items-center justify-center hover:bg-[var(--fill-tsp-white-dark)] rounded-lg cursor-pointer"
              >
                <LinkIcon className="text-[var(--icon-secondary)]" size={20} />
              </button>
              <button
                onClick={() => showSessionFileList(true)}
                className="p-2 flex items-center justify-center hover:bg-[var(--fill-tsp-white-dark)] rounded-lg cursor-pointer"
              >
                <FileSearch className="text-[var(--icon-secondary)]" size={20} />
              </button>
            </div>
          </div>
        </header>

        <div className="mx-auto w-full max-w-full sm:max-w-[768px] sm:min-w-[390px] flex flex-col flex-1">
          {plan && plan.tasks?.length > 0 && (
            <div className="sticky top-0 z-10 pt-2 pb-1 bg-[var(--background-gray-main)]">
              <PlanPanel plan={plan} />
            </div>
          )}
          <div className="flex flex-col w-full gap-[12px] pb-[80px] pt-[12px] flex-1 overflow-y-auto">
            {renderedMessages}
            {isLoading && <LoadingIndicator text="Thinking" />}
          </div>

          <div className="sticky bottom-0 max-w-[800px] mx-auto w-full pb-3 flex flex-col gap-2 px-3 pt-2.5 sm:pt-0">
            {!follow && (
              <button
                onClick={handleFollow}
                className="flex items-center justify-center w-9 h-9 rounded-full bg-[var(--background-white-main)] cursor-pointer border border-[var(--border-main)] shadow-[0px_5px_16px_0px_var(--shadow-S)] absolute -top-20 left-1/2 -translate-x-1/2"
              >
                <ArrowDown className="text-[var(--icon-primary)]" size={20} />
              </button>
            )}
            <div className="bg-[var(--background-white-main)] rounded-xl border border-[var(--border-main)] shadow-[0px_5px_16px_0px_var(--shadow-S),0px_0px_1.25px_0px_var(--shadow-XS)] backdrop-blur-3xl flex items-center justify-between py-[9px] pr-3 pl-4 sm:flex-row flex-col max-sm:gap-3 max-sm:p-2">
              <div className="flex items-center gap-0.5 w-full sm:flex-1">
                <div className="w-6 h-6">
                  <Bot size={24} />
                </div>
                <p className="text-sm text-[var(--text-primary)] ml-1">
                  {replayCompleted ? 'Replay complete.' : 'Replaying task...'}
                </p>
              </div>
              <div className="flex items-center flex-row gap-[8px] max-sm:w-full">
                <button
                  onClick={() => (replayCompleted ? void replay() : (jumpToEnd.current = true))}
                  className="inline-flex items-center justify-center whitespace-nowrap font-medium hover:opacity-90 bg-[var(--Button-primary-brand)] text-[var(--text-white)] h-9 rounded-[10px] gap-[6px] text-sm px-[14px] max-sm:w-1/2"
                >
                  <span className="text-sm">{replayCompleted ? 'Replay' : 'Jump to end'}</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {showReplayOverlay && (
        <div
          className="fixed bottom-0 left-0 right-0 z-50 flex items-center justify-center"
          style={{
            height: 'calc(-156px + 100vh)',
            background:
              'linear-gradient(rgba(255, 255, 255, 0) 5.99%, rgb(255, 255, 255) 35.84%)',
          }}
        >
          <div className="flex flex-col items-center gap-4 p-2.5">
            <button
              onClick={startReplay}
              className="flex items-center justify-center rounded-full bg-[var(--Button-primary-black)] p-3 cursor-pointer animate-pulse hover:opacity-85"
            >
              <Play size={24} className="text-[var(--text-onblack)]" />
            </button>
            <div className="text-center text-[var(--text-primary)] whitespace-pre-line">
              You are viewing a completed Helix task. Replay will start automatically in{' '}
              <strong>{countdown}</strong> seconds.
            </div>
          </div>
        </div>
      )}

      <ToolPanel
        ref={toolPanel}
        sessionId={sessionId}
        realTime={realTime}
        isShare
        onJumpToRealTime={jumpToRealTime}
      />
    </SimpleBar>
  )
}
