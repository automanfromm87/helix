import { useState } from 'react'
import { Check, ChevronDown, Minimize2, Play } from 'lucide-react'

import { useToolInfo } from '@/hooks/useTool'
import type { ToolContent } from '@/types/message'
import { TOOL_ICON_MAP, TOOL_NAME_MAP } from '@/constants/tool'
import { Popover, PopoverContent, PopoverTrigger } from './ui/Popover'
import { cn } from '@/lib/utils'

interface Props {
  sessionId: string
  realTime: boolean
  toolContent: ToolContent
  live: boolean
  isShare: boolean
  /**
   * Map of tool category (`shell` / `file` / `browser` / `search` / `mcp`)
   * to the most recent tool content of that category. Powers the manual view
   * switcher dropdown so the user can jump back to e.g. the latest browser
   * snapshot after the agent moved on.
   */
  availableViews: Record<string, ToolContent>
  onSwitchView: (content: ToolContent) => void
  onHide: () => void
  onJumpToRealTime: () => void
}

const VIEW_ORDER: ReadonlyArray<string> = ['browser', 'file', 'shell', 'search', 'mcp']

export default function ToolPanelContent({
  sessionId,
  realTime,
  toolContent,
  live,
  isShare,
  availableViews,
  onSwitchView,
  onHide,
  onJumpToRealTime,
}: Props) {
  const toolInfo = useToolInfo(toolContent)
  const View = toolInfo?.View
  const Icon = toolInfo?.Icon

  /** Dropdown options in stable, human-friendly order. */
  const dropdownOptions = VIEW_ORDER.filter((k) => k in availableViews)

  const [open, setOpen] = useState(false)
  const currentCategory = toolContent.name
  const hasMultipleViews = dropdownOptions.length > 1

  return (
    <div className="bg-[var(--background-gray-main)] sm:bg-[var(--background-menu-white)] sm:rounded-[22px] shadow-[0px_0px_8px_0px_rgba(0,0,0,0.02)] border border-black/8 dark:border-[var(--border-light)] flex h-full w-full">
      <div className="flex-1 min-w-0 p-4 flex flex-col h-full">
        <div className="flex items-center gap-2 w-full">
          {hasMultipleViews ? (
            <Popover open={open} onOpenChange={setOpen}>
              <PopoverTrigger asChild>
                <button className="flex-1 flex items-center gap-1.5 text-left text-[var(--text-primary)] text-lg font-semibold rounded-md px-1.5 -mx-1.5 py-0.5 cursor-pointer hover:bg-[var(--fill-tsp-gray-main)]">
                  <span>Helix Computer</span>
                  <span className="text-sm font-normal text-[var(--text-tertiary)]">
                    · {TOOL_NAME_MAP[currentCategory] ?? currentCategory}
                  </span>
                  <ChevronDown
                    size={16}
                    className={cn(
                      'text-[var(--icon-tertiary)] transition-transform',
                      open && 'rotate-180',
                    )}
                  />
                </button>
              </PopoverTrigger>
              <PopoverContent align="start" sideOffset={6}>
                <div className="w-[320px] max-w-[calc(100vw-32px)] rounded-xl border border-[var(--border-light)] bg-[var(--background-menu-white)] shadow-[0px_8px_32px_0px_var(--shadow-S)] py-1">
                  {dropdownOptions.map((category) => {
                    const item = availableViews[category]
                    const ItemIcon = TOOL_ICON_MAP[category]
                    const isSelected = category === currentCategory
                    const argPreview =
                      typeof item.args === 'object'
                        ? Object.values(item.args).find((v) => typeof v === 'string')
                        : undefined
                    return (
                      <button
                        key={category}
                        onClick={() => {
                          onSwitchView(item)
                          setOpen(false)
                        }}
                        className={cn(
                          'w-full flex items-center gap-2.5 px-3 py-2 text-left hover:bg-[var(--fill-tsp-white-main)]',
                          isSelected && 'bg-[var(--fill-tsp-white-light)]',
                        )}
                      >
                        <div className="w-7 h-7 bg-[var(--fill-tsp-gray-main)] rounded-md flex items-center justify-center flex-shrink-0">
                          {ItemIcon ? <ItemIcon size={18} /> : null}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="text-sm font-medium text-[var(--text-primary)]">
                            {TOOL_NAME_MAP[category] ?? category}
                          </div>
                          {typeof argPreview === 'string' && (
                            <div className="text-xs text-[var(--text-tertiary)] truncate">
                              {argPreview}
                            </div>
                          )}
                        </div>
                        {isSelected && (
                          <Check size={16} className="text-[var(--icon-primary)] flex-shrink-0" />
                        )}
                      </button>
                    )
                  })}
                </div>
              </PopoverContent>
            </Popover>
          ) : (
            <div className="text-[var(--text-primary)] text-lg font-semibold flex-1">
              Helix Computer
            </div>
          )}
          <button
            onClick={onHide}
            className="w-7 h-7 rounded-md inline-flex items-center justify-center cursor-pointer hover:bg-[var(--fill-tsp-gray-main)]"
          >
            <Minimize2 className="w-5 h-5 text-[var(--icon-tertiary)]" />
          </button>
        </div>
        {toolInfo && (
          <div className="flex items-center gap-2 mt-2">
            <div className="w-[40px] h-[40px] bg-[var(--fill-tsp-gray-main)] rounded-lg flex items-center justify-center flex-shrink-0">
              {Icon ? <Icon size={28} /> : null}
            </div>
            <div className="flex-1 flex flex-col gap-1 min-w-0">
              <div className="text-[12px] text-[var(--text-tertiary)]">
                Helix is using <span className="text-[var(--text-secondary)]">{toolInfo.name}</span>
              </div>
              <div
                title={`${toolInfo.function} ${toolInfo.functionArg}`}
                className="max-w-[100%] w-[max-content] truncate text-[13px] rounded-full inline-flex items-center px-[10px] py-[3px] border border-[var(--border-light)] bg-[var(--fill-tsp-gray-main)] text-[var(--text-secondary)]"
              >
                {toolInfo.function}
                <span className="flex-1 min-w-0 px-1 ml-1 text-[12px] font-mono max-w-full text-ellipsis overflow-hidden whitespace-nowrap text-[var(--text-tertiary)]">
                  <code>{toolInfo.functionArg}</code>
                </span>
              </div>
            </div>
          </div>
        )}
        <div className="relative flex flex-col rounded-[12px] overflow-hidden bg-[var(--background-gray-main)] border border-[var(--border-dark)] dark:border-black/30 shadow-[0px_4px_32px_0px_rgba(0,0,0,0.04)] flex-1 min-h-0 mt-[16px]">
          {View ? (
            <View
              sessionId={sessionId}
              toolContent={toolContent}
              live={live}
              isShare={isShare}
            />
          ) : null}
          {!realTime && (
            <button
              onClick={onJumpToRealTime}
              className="h-10 px-3 border border-[var(--border-main)] flex items-center gap-1 bg-[var(--background-white-main)] hover:bg-[var(--background-gray-main)] shadow-[0px_5px_16px_0px_var(--shadow-S),0px_0px_1.25px_0px_var(--shadow-S)] rounded-full cursor-pointer absolute bottom-3 left-1/2 -translate-x-1/2"
            >
              <Play size={16} />
              <span className="text-[var(--text-primary)] text-sm font-medium">Jump to live</span>
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
