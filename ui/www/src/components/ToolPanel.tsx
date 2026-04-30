import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from 'react'

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

    return (
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
    )
  },
)

ToolPanel.displayName = 'ToolPanel'

export default ToolPanel
