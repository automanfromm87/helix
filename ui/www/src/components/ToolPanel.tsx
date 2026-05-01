import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from 'react'
import { PanelRightOpen } from 'lucide-react'

import type { ToolContent } from '@/types/message'
import ToolPanelContent from './ToolPanelContent'
import { useResizeObserver } from '@/hooks/useResizeObserver'
import { eventBus } from '@/utils/eventBus'
import { EVENT_SHOW_FILE_PANEL, EVENT_SHOW_TOOL_PANEL } from '@/constants/event'

interface Props {
  sessionId?: string
  realTime: boolean
  isShare: boolean
  onJumpToRealTime: () => void
}

export interface ToolPanelHandle {
  showToolPanel: (content: ToolContent, isLive?: boolean) => void
  hideToolPanel: () => void
  isShow: () => boolean
}

const ToolPanel = forwardRef<ToolPanelHandle, Props>(
  ({ sessionId, realTime, isShare, onJumpToRealTime }, ref) => {
    const containerRef = useRef<HTMLDivElement>(null)
    const { size: parentSize } = useResizeObserver(containerRef, {
      target: 'parent',
      property: 'width',
    })

    const [isShow, setIsShow] = useState(false)
    const [live, setLive] = useState(false)
    const [toolContent, setToolContent] = useState<ToolContent | undefined>()
    const [visible, setVisible] = useState(true)
    /**
     * Track the most recent ToolContent for each tool category that has been
     * surfaced so far. This powers the manual view-switcher dropdown so the
     * user can re-open e.g. the Browser snapshot even after the agent moved on
     * to a Shell command.
     */
    const [availableViews, setAvailableViews] = useState<Record<string, ToolContent>>({})

    const showToolPanel = useCallback((content: ToolContent, isLive: boolean = false) => {
      eventBus.emit(EVENT_SHOW_TOOL_PANEL)
      setVisible(true)
      setToolContent(content)
      setIsShow(true)
      setLive(isLive)
      setAvailableViews((prev) => {
        // Same reference (or same tool_call_id snapshot) → skip the spread to
        // avoid a no-op rerender of the dropdown's useMemo downstream.
        if (prev[content.name] === content) return prev
        return { ...prev, [content.name]: content }
      })
    }, [])

    const hideToolPanel = useCallback(() => setIsShow(false), [])

    // Reopen with the most recently surfaced tool content. Used by the
    // floating reopen tab so the user has a way back after they close the
    // panel without scrolling the chat to find a tool message.
    const reopenLast = useCallback(() => {
      if (toolContent) {
        showToolPanel(toolContent, live)
      }
    }, [toolContent, live, showToolPanel])

    /** Manual view switch from the dropdown — never live, since the user is navigating history. */
    const switchView = useCallback((content: ToolContent) => {
      setToolContent(content)
      setLive(false)
    }, [])

    useEffect(() => {
      const off = eventBus.on(EVENT_SHOW_FILE_PANEL, () => setVisible(false))
      return () => off()
    }, [])

    useImperativeHandle(ref, () => ({
      showToolPanel,
      hideToolPanel,
      isShow: () => isShow,
    }))

    if (!visible) return null

    // When the panel is collapsed but a tool has previously been shown,
    // render a small vertical handle pinned to the right edge so the user
    // can re-open it without scrolling the chat to find a tool message.
    const showReopenTab = !isShow && Boolean(toolContent) && Boolean(sessionId)

    return (
      <>
        <div
          ref={containerRef}
          className={
            isShow
              ? 'h-full w-full top-0 ltr:right-0 rtl:left-0 z-50 fixed sm:sticky sm:top-0 sm:right-0 sm:h-[100vh] sm:ml-3 sm:py-3 sm:mr-4'
              : 'h-full overflow-hidden'
          }
          style={{
            width: isShow ? `${parentSize / 2}px` : '0px',
            opacity: isShow ? 1 : 0,
            transition: '0.2s ease-in-out',
          }}
        >
          <div className="h-full" style={{ width: isShow ? '100%' : '0px' }}>
            {isShow && toolContent && sessionId && (
              <ToolPanelContent
                sessionId={sessionId}
                realTime={realTime}
                toolContent={toolContent}
                live={live}
                isShare={isShare}
                availableViews={availableViews}
                onSwitchView={switchView}
                onHide={hideToolPanel}
                onJumpToRealTime={onJumpToRealTime}
              />
            )}
          </div>
        </div>
        {showReopenTab && (
          <button
            type="button"
            onClick={reopenLast}
            title="Show Helix Computer"
            aria-label="Show Helix Computer panel"
            className="hidden sm:flex fixed right-0 top-1/2 -translate-y-1/2 z-40 items-center gap-1.5 px-2 py-3 rounded-l-lg border border-r-0 border-[var(--border-main)] bg-[var(--background-menu-white)] text-[var(--text-secondary)] shadow-[0px_4px_16px_0px_rgba(0,0,0,0.06)] hover:bg-[var(--fill-tsp-white-light)] hover:text-[var(--text-primary)] transition-colors"
          >
            <PanelRightOpen size={16} />
          </button>
        )}
      </>
    )
  },
)

ToolPanel.displayName = 'ToolPanel'

export default ToolPanel
