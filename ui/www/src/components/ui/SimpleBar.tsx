import 'simplebar-react/dist/simplebar.min.css'
import SimpleBarReact from 'simplebar-react'
import {
  forwardRef,
  useImperativeHandle,
  useRef,
  type ReactNode,
  type UIEvent,
} from 'react'

import { cn } from '@/lib/utils'

export interface SimpleBarHandle {
  scrollToBottom: () => void
  isScrolledToBottom: () => boolean
  getScrollElement: () => HTMLElement | null
}

interface SimpleBarProps {
  className?: string
  children?: ReactNode
  onScroll?: (event: UIEvent<HTMLElement>) => void
}

/**
 * Wrapper around simplebar-react.
 *
 * Replicates the Vue SimpleBar.vue Tailwind layout so that direct children
 * (e.g. ChatPage's main column + ToolPanel) lay out as flex-row siblings.
 * Without this, sticky positioning on the right-hand panel collapses and
 * everything stacks vertically.
 */
export const SimpleBar = forwardRef<SimpleBarHandle, SimpleBarProps>(
  ({ className, children, onScroll }, ref) => {
    const innerRef = useRef<any>(null)

    useImperativeHandle(ref, () => ({
      scrollToBottom: () => {
        const el = innerRef.current?.getScrollElement?.() as HTMLElement | undefined
        if (el) el.scrollTop = el.scrollHeight
      },
      isScrolledToBottom: () => {
        const el = innerRef.current?.getScrollElement?.() as HTMLElement | undefined
        if (!el) return true
        return el.scrollHeight - el.scrollTop - el.clientHeight < 4
      },
      getScrollElement: () => innerRef.current?.getScrollElement?.() ?? null,
    }))

    return (
      <SimpleBarReact
        ref={innerRef}
        scrollableNodeProps={onScroll ? { onScroll } : undefined}
        className={cn(
          'flex flex-1 min-w-0 h-full simplebar-scrollable-y',
          '[&_.simplebar-content-wrapper]:flex [&_.simplebar-content-wrapper]:flex-col [&_.simplebar-content-wrapper]:h-full',
          '[&_.simplebar-content]:flex [&_.simplebar-content]:flex-1 [&_.simplebar-content]:flex-row',
          className,
        )}
      >
        {children}
      </SimpleBarReact>
    )
  },
)
SimpleBar.displayName = 'SimpleBar'
