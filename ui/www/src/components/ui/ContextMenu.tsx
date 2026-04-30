import { useEffect, useRef, useState } from 'react'
import { useContextMenu } from '@/hooks/useContextMenu'
import { cn } from '@/lib/utils'

/** Globally-mounted context menu controlled by useContextMenu store. */
export default function ContextMenu() {
  const { visible, items, targetElement, handleItemClick, hide } = useContextMenu()
  const [position, setPosition] = useState<{ x: number; y: number } | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!visible || !targetElement) {
      setPosition(null)
      return
    }
    const rect = targetElement.getBoundingClientRect()
    setPosition({ x: rect.right - 160, y: rect.bottom + 4 })

    // Ignore mousedowns on the trigger AND inside the menu itself, otherwise
    // the menu unmounts before the item's click can fire.
    const handleDocClick = (event: MouseEvent) => {
      const target = event.target
      if (!(target instanceof Node)) return
      if (targetElement.contains(target)) return
      if (menuRef.current?.contains(target)) return
      hide()
    }
    const handleEsc = (e: KeyboardEvent) => e.key === 'Escape' && hide()

    document.addEventListener('mousedown', handleDocClick)
    document.addEventListener('keydown', handleEsc)
    return () => {
      document.removeEventListener('mousedown', handleDocClick)
      document.removeEventListener('keydown', handleEsc)
    }
  }, [visible, targetElement, hide])

  if (!visible || !position) return null

  return (
    <div
      ref={menuRef}
      role="menu"
      style={{ top: position.y, left: position.x }}
      className="fixed z-[60] min-w-[160px] rounded-xl border border-[var(--border-light)] bg-[var(--background-menu-white)] py-1 shadow-[0px_8px_32px_0px_var(--shadow-S)]"
    >
      {items.map((item) => {
        if (item.key === 'separator') {
          return <div key="sep" className="my-1 h-px bg-[var(--border-light)]" />
        }
        const Icon = item.icon
        return (
          <button
            key={item.key}
            disabled={item.disabled}
            onClick={() => handleItemClick(item)}
            className={cn(
              'flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-[var(--fill-tsp-white-main)] disabled:opacity-50 disabled:hover:bg-transparent',
              item.variant === 'danger'
                ? 'text-[var(--function-error)]'
                : 'text-[var(--text-primary)]',
            )}
          >
            {Icon ? <Icon size={16} /> : null}
            <span>{item.label}</span>
          </button>
        )
      })}
    </div>
  )
}
