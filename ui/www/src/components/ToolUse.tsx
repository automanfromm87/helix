import type { ToolContent } from '@/types/message'
import { useToolInfo } from '@/hooks/useTool'
import { useRelativeTime } from '@/hooks/useTime'

interface Props {
  tool: ToolContent
  onClick?: () => void
}

export default function ToolUse({ tool, onClick }: Props) {
  const toolInfo = useToolInfo(tool)
  const { relativeTime } = useRelativeTime()

  if (tool.name === 'message' && tool.args?.text) {
    return (
      <p className="text-[var(--text-secondary)] text-[14px] overflow-hidden text-ellipsis whitespace-pre-line">
        {tool.args.text}
      </p>
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
