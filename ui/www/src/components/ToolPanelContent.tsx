import { useState } from 'react'
import { ChevronDown, Minimize2, Play } from 'lucide-react'

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

// Preview goes first — it's the dropdown default for any session that
// has a dev server. Browser (VNC) follows for the agent's headless
// chrome view. The rest are the agent's working tools.
const VIEW_ORDER: ReadonlyArray<string> = ['preview', 'browser', 'file', 'shell', 'search', 'mcp']

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

  /** Dropdown options in stable, human-friendly order.
   *
   * `preview` and `browser` are always available — the user wants to
   * peek at the running app / sandbox VNC even before the agent surfaces
   * any tool of those categories. The rest (file/shell/search/mcp) only
   * appear after the agent actually calls them.
   */
  const dropdownOptions = VIEW_ORDER.filter(
    (k) => k in availableViews || k === 'browser' || k === 'preview',
  )

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
              <PopoverContent align="start" sideOffset={8}>
                <div className="w-[340px] max-w-[calc(100vw-32px)] rounded-xl border border-[var(--border-light)] bg-[var(--background-menu-white)] shadow-[0px_8px_32px_0px_var(--shadow-S)] p-1.5">
                  {dropdownOptions.map((category) => {
                    const item =
                      availableViews[category] ??
                      // Synthetic placeholder so the user can open Browser
                      // (or any other view) before the agent has actually
                      // called a tool of that category. The view component
                      // is responsible for tolerating an empty args bag —
                      // BrowserToolView for instance just opens about:blank
                      // / the live preview when no navigate target is set.
                      ({
                        tool_call_id: `synthetic-${category}`,
                        name: category,
                        function: '',
                        args: {},
                        status: 'called',
                        timestamp: Date.now(),
                      } as ToolContent)
                    const ItemIcon = TOOL_ICON_MAP[category]
                    const isSelected = category === currentCategory
                    return (
                      <button
                        key={category}
                        onClick={() => {
                          onSwitchView(item)
                          setOpen(false)
                        }}
                        className={cn(
                          'relative w-full h-10 flex items-center gap-3 pl-3 pr-2.5 rounded-lg text-left transition-colors',
                          'hover:bg-[var(--fill-tsp-white-main)]',
                          isSelected && 'bg-[var(--fill-tsp-white-light)]',
                        )}
                      >
                        <span
                          className={cn(
                            'absolute left-0 top-2 bottom-2 w-[3px] rounded-r-full transition-opacity',
                            isSelected
                              ? 'bg-[var(--text-brand)] opacity-100'
                              : 'opacity-0',
                          )}
                          aria-hidden
                        />
                        {ItemIcon ? (
                          <ItemIcon
                            size={16}
                            className={cn(
                              'flex-shrink-0',
                              isSelected
                                ? 'text-[var(--text-brand)]'
                                : 'text-[var(--icon-secondary)]',
                            )}
                          />
                        ) : null}
                        <div
                          className={cn(
                            'flex-1 min-w-0 text-[13px] text-[var(--text-primary)]',
                            isSelected ? 'font-semibold' : 'font-medium',
                          )}
                        >
                          {TOOL_NAME_MAP[category] ?? category}
                        </div>
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
          <div className="flex items-center gap-2 mt-2 min-w-0">
            <span
              className={cn(
                'w-2 h-2 rounded-full flex-shrink-0',
                live
                  ? 'bg-[var(--text-brand)] animate-pulse'
                  : 'bg-[var(--icon-tertiary)]',
              )}
              aria-hidden
            />
            <span className="text-[12px] text-[var(--text-tertiary)] flex-shrink-0">
              Using
            </span>
            <span className="text-[12px] font-medium text-[var(--text-secondary)] flex-shrink-0">
              {toolInfo.name}
            </span>
            {(toolInfo.function || toolInfo.functionArg) && (
              <span
                title={`${toolInfo.function} ${toolInfo.functionArg}`}
                className="min-w-0 max-w-full truncate inline-flex items-center px-2 py-[2px] rounded-md border border-[var(--border-light)] bg-[var(--fill-tsp-gray-main)] text-[12px] text-[var(--text-secondary)]"
              >
                {toolInfo.function && (
                  <span className="flex-shrink-0">{toolInfo.function}</span>
                )}
                {toolInfo.functionArg && (
                  <span className="ml-1 min-w-0 truncate font-mono text-[11px] text-[var(--text-tertiary)]">
                    {toolInfo.functionArg}
                  </span>
                )}
              </span>
            )}
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
