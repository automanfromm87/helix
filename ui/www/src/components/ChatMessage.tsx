import { useState, type ComponentType } from 'react'
import { Bot, ChevronDown, Check, Pencil } from 'lucide-react'

import {
  type AttachmentsContent,
  type Message,
  type MessageContent,
  type TaskContent,
  type ToolContent,
} from '@/types/message'
import { useRelativeTime } from '@/hooks/useTime'
import { HelixTextIcon } from '@/components/icons'
import AttachmentsMessage from './AttachmentsMessage'
import CollapsibleMarkdown from './CollapsibleMarkdown'
import Markdown from './Markdown'
import ToolUse from './ToolUse'
import { cn } from '@/lib/utils'

interface Props {
  message: Message
  sessionId?: string
  assistantIcon?: ComponentType<{ size?: number; className?: string }>
  assistantName?: string
  hideAllFilesButton?: boolean
  hideHeader?: boolean
  onToolClick?: (tool: ToolContent) => void
  onEditUserMessage?: (eventId: string, newMessage: string) => void
}

export default function ChatMessage({
  message,
  assistantIcon: AssistantIcon,
  assistantName,
  hideAllFilesButton,
  hideHeader,
  onToolClick,
  onEditUserMessage,
}: Props) {
  const { relativeTime } = useRelativeTime()
  const [isExpanded, setIsExpanded] = useState(true)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const hideAssistantHeader = hideHeader ?? false

  if (message.type === 'user') {
    const content = message.content as MessageContent
    const canEdit = Boolean(onEditUserMessage && content.event_id)
    const startEdit = () => {
      setDraft(content.content)
      setEditing(true)
    }
    const submitEdit = () => {
      const trimmed = draft.trim()
      if (!trimmed || trimmed === content.content) {
        setEditing(false)
        return
      }
      if (content.event_id) onEditUserMessage?.(content.event_id, trimmed)
      setEditing(false)
    }
    return (
      <div className="flex w-full flex-col items-end justify-end gap-1 group mt-3">
        <div className="flex items-end">
          <div className="flex items-center justify-end gap-[2px] invisible group-hover:visible">
            <div className="float-right transition text-[12px] text-[var(--text-tertiary)] invisible group-hover:visible">
              {relativeTime(message.content.timestamp)}
            </div>
          </div>
        </div>
        <div className="flex max-w-[90%] relative flex-col gap-2 items-end">
          {editing ? (
            <div className="flex flex-col gap-2 w-full max-w-[600px]">
              <textarea
                autoFocus
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    submitEdit()
                  } else if (e.key === 'Escape') {
                    setEditing(false)
                  }
                }}
                className="w-full rounded-[12px] border border-[var(--border-main)] bg-[var(--fill-white)] dark:bg-[var(--fill-tsp-white-main)] p-3 text-sm resize-none outline-none focus:ring-2 focus:ring-[var(--text-brand)]"
                rows={Math.min(8, Math.max(2, draft.split('\n').length))}
              />
              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => setEditing(false)}
                  className="px-3 h-8 rounded-md text-sm border border-[var(--border-btn-main)] hover:bg-[var(--fill-tsp-white-light)]"
                >
                  Cancel
                </button>
                <button
                  onClick={submitEdit}
                  className="px-3 h-8 rounded-md text-sm bg-[var(--Button-primary-black)] text-[var(--text-onblack)] hover:opacity-90"
                >
                  Send
                </button>
              </div>
            </div>
          ) : (
            <div className="relative flex items-center gap-1.5">
              {canEdit && (
                <button
                  onClick={startEdit}
                  title="Edit & regenerate"
                  className="opacity-0 group-hover:opacity-100 transition flex items-center justify-center size-7 rounded-md hover:bg-[var(--fill-tsp-white-light)] text-[var(--icon-tertiary)]"
                >
                  <Pencil size={14} />
                </button>
              )}
              <Markdown
                content={content.content}
                className="relative flex items-center rounded-[12px] overflow-hidden bg-[var(--fill-white)] dark:bg-[var(--fill-tsp-white-main)] p-3 ltr:rounded-br-none rtl:rounded-bl-none border border-[var(--border-main)] dark:border-0"
              />
            </div>
          )}
        </div>
      </div>
    )
  }

  if (message.type === 'assistant') {
    const content = message.content as MessageContent
    return (
      <div
        className={cn('flex flex-col gap-2 w-full group', hideAssistantHeader ? 'mt-0' : 'mt-3')}
      >
        {!hideAssistantHeader && (
          <div className="flex items-center justify-between h-7 group">
            <div className="flex items-center gap-[3px]">
              {AssistantIcon ? (
                <AssistantIcon size={24} className="w-6 h-6" />
              ) : (
                <Bot size={24} className="w-6 h-6" />
              )}
              {assistantName ? (
                <span className="text-base text-[var(--text-primary)] tracking-tight leading-none ml-0.5">
                  {assistantName}
                </span>
              ) : !AssistantIcon ? (
                <HelixTextIcon />
              ) : null}
            </div>
            <div className="flex items-center gap-[2px] invisible group-hover:visible">
              <div className="float-right transition text-[12px] text-[var(--text-tertiary)] invisible group-hover:visible">
                {relativeTime(message.content.timestamp)}
              </div>
            </div>
          </div>
        )}
        {/* Long assistant turns (e.g. the model dumping a 50KB README) get
         * default-collapsed to a head preview to keep DOM weight bounded.
         * Streaming partials stay below threshold during typical turns. */}
        <CollapsibleMarkdown
          content={content.content}
          partial={content.partial ?? false}
          className="max-w-none p-0 m-0 prose prose-sm sm:prose-base dark:prose-invert [&_pre:not(.shiki)]:!bg-[var(--fill-tsp-white-light)] [&_pre:not(.shiki)]:text-[var(--text-primary)] text-base text-[var(--text-primary)]"
        />
      </div>
    )
  }

  if (message.type === 'tool') {
    const tool = message.content as ToolContent
    return <ToolUse tool={tool} onClick={() => onToolClick?.(tool)} />
  }

  if (message.type === 'task') {
    const task = message.content as TaskContent
    const isDone = task.status === 'completed'
    const isFailed = task.status === 'failed' || task.status === 'blocked'
    return (
      <div className="flex flex-col">
        <div className="text-sm w-full cursor-pointer flex gap-2 justify-between group/header truncate text-[var(--text-primary)]">
          <div className="flex flex-row gap-2 justify-center items-center truncate">
            {isDone ? (
              <div className="w-4 h-4 flex-shrink-0 flex items-center justify-center rounded-[15px] bg-[var(--function-success)]">
                <Check size={10} className="text-white" />
              </div>
            ) : isFailed ? (
              <div className="w-4 h-4 flex-shrink-0 flex items-center justify-center rounded-[15px] bg-[var(--function-error)]" />
            ) : (
              <div className="w-4 h-4 flex-shrink-0 flex items-center justify-center border border-[var(--border-dark)] rounded-[15px]" />
            )}
            <span className="truncate font-medium">
              {task.title}
            </span>
            <button
              type="button"
              className="flex-shrink-0 flex"
              onClick={() => setIsExpanded(!isExpanded)}
            >
              <ChevronDown
                size={16}
                className={cn(
                  'transition-transform duration-300',
                  isExpanded ? 'rotate-180' : 'rotate-0',
                )}
              />
            </button>
          </div>
          <div className="float-right transition text-[12px] text-[var(--text-tertiary)] invisible group-hover/header:visible">
            {relativeTime(message.content.timestamp)}
          </div>
        </div>
        <div className="flex">
          <div className="w-[24px] relative">
            <div
              className="border-l border-dashed border-[var(--border-dark)] absolute start-[8px] top-0 bottom-0"
              style={{ height: 'calc(100% + 14px)' }}
            />
          </div>
          <div
            className={cn(
              'flex flex-col gap-3 flex-1 min-w-0 overflow-hidden pt-2 transition-all duration-150 ease-in-out',
              isExpanded ? 'max-h-[100000px] opacity-100' : 'max-h-0 opacity-0',
            )}
          >
            {task.tools.map((tool, index) => (
              <ToolUse key={index} tool={tool} onClick={() => onToolClick?.(tool)} />
            ))}
          </div>
        </div>
      </div>
    )
  }

  if (message.type === 'attachments') {
    const att = message.content as AttachmentsContent
    if (att.role === 'assistant') {
      return (
        <div
          className={cn(
            'flex flex-col gap-2 w-full group',
            hideAssistantHeader ? 'mt-0' : 'mt-3',
          )}
        >
          {!hideAssistantHeader && (
            <div className="flex items-center justify-between h-7 group">
              <div className="flex items-center gap-[3px]">
                {AssistantIcon ? (
                  <AssistantIcon size={24} className="w-6 h-6" />
                ) : (
                  <Bot size={24} className="w-6 h-6" />
                )}
                {assistantName ? (
                  <span className="text-base text-[var(--text-primary)] tracking-tight leading-none ml-0.5">
                    {assistantName}
                  </span>
                ) : !AssistantIcon ? (
                  <HelixTextIcon />
                ) : null}
              </div>
              <div className="flex items-center gap-[2px] invisible group-hover:visible">
                <div className="float-right transition text-[12px] text-[var(--text-tertiary)] invisible group-hover:visible">
                  {relativeTime(att.timestamp)}
                </div>
              </div>
            </div>
          )}
          <AttachmentsMessage content={att} hideAllFilesButton={hideAllFilesButton} />
        </div>
      )
    }
    return <AttachmentsMessage content={att} hideAllFilesButton={hideAllFilesButton} />
  }

  return null
}
