import type { ToolContent } from '@/types/message'
import { useToolInfo } from '@/hooks/useTool'
import { useRelativeTime } from '@/hooks/useTime'

interface Props {
  tool: ToolContent
  onClick?: () => void
}

/**
 * Single-source-of-truth event name for "user clicked an option button
 * inside an `message_ask_user` tool render". Picked up in ChatPage,
 * which dispatches the option text through the regular `chat()` path.
 * A window event is the lightest decoupling between the deeply-nested
 * render tree (Message → Tool → ToolUse) and the chat dispatcher,
 * matching the existing `helix:preview:select` convention.
 */
export const REPLY_WITH_OPTION_EVENT = 'helix:reply-with-option'

export default function ToolUse({ tool, onClick }: Props) {
  const toolInfo = useToolInfo(tool)
  const { relativeTime } = useRelativeTime()

  if (tool.name === 'message' && tool.args?.text) {
    const opts: unknown = tool.args.options
    const options: string[] = Array.isArray(opts)
      ? opts.filter((o): o is string => typeof o === 'string' && o.trim().length > 0)
      : []
    const isAskUser = tool.function === 'message_ask_user'
    return (
      <div className="flex flex-col gap-2">
        <p className="text-[var(--text-secondary)] text-[14px] whitespace-pre-line">
          {tool.args.text}
        </p>
        {isAskUser && options.length > 0 && (
          <div className="flex flex-wrap gap-2 mt-1">
            {options.map((opt, i) => (
              <button
                key={i}
                type="button"
                onClick={() => {
                  // Stop propagation so click doesn't also fire the
                  // outer message-row's onClick (which opens the tool
                  // panel and would feel mispredicted here).
                  window.dispatchEvent(
                    new CustomEvent(REPLY_WITH_OPTION_EVENT, { detail: opt }),
                  )
                }}
                className="inline-flex items-center max-w-full text-left px-3 py-1.5 rounded-md border border-[var(--border-btn-main)] bg-[var(--fill-tsp-white-light)] text-[13px] text-[var(--text-primary)] hover:bg-[var(--text-brand)] hover:text-white hover:border-[var(--text-brand)] transition-colors"
              >
                <span className="truncate">{opt}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    )
  }

  if (!toolInfo) return null
  const { Icon } = toolInfo

  return (
    <div className="flex items-center group gap-2">
      <div className="flex-1 min-w-0">
        <div
          onClick={onClick}
          className="rounded-[15px] items-center gap-2 px-[10px] py-[3px] border border-[var(--border-light)] bg-[var(--fill-tsp-gray-main)] inline-flex max-w-full cursor-pointer hover:bg-[var(--fill-tsp-gray-dark)] dark:hover:bg-white/[0.02]"
        >
          <div className="w-[16px] inline-flex items-center text-[var(--text-primary)]">
            {Icon ? <Icon size={21} /> : null}
          </div>
          <div className="flex-1 h-full min-w-0 flex">
            <div className="inline-flex items-center h-full rounded-full text-[14px] text-[var(--text-secondary)] max-w-[100%]">
              <div
                className="max-w-[100%] text-ellipsis overflow-hidden whitespace-nowrap text-[13px]"
                title={`${toolInfo.function} ${toolInfo.functionArg}`.trim()}
              >
                <div className="flex items-center">
                  {toolInfo.function}
                  <span className="flex-1 min-w-0 rounded-[6px] px-1 ml-1 relative top-[0px] text-[12px] font-mono max-w-full text-ellipsis overflow-hidden whitespace-nowrap text-[var(--text-tertiary)]">
                    <code>{toolInfo.functionArg}</code>
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div className="float-right transition text-[12px] text-[var(--text-tertiary)] invisible group-hover:visible">
        {relativeTime(tool.timestamp)}
      </div>
    </div>
  )
}
