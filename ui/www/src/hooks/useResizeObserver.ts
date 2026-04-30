import { useEffect, useState, type RefObject } from 'react'
import { getParentElement } from '@/utils/dom'

interface Options {
  target?: 'self' | 'parent'
  property?: 'width' | 'height'
  callback?: (size: number) => void
}

/**
 * Observe size of either the ref'd element or its parent.
 * Mirrors the Vue composables/useResizeObserver.ts behavior.
 */
export function useResizeObserver<T extends HTMLElement>(
  targetRef: RefObject<T>,
  options: Options = {},
) {
  const { target = 'parent', property = 'width', callback } = options
  const [size, setSize] = useState(0)

  useEffect(() => {
    const current = targetRef.current
    if (!current) return

    const observed: HTMLElement | null =
      target === 'parent' ? getParentElement(current) : current
    if (!observed) return

    const update = () => {
      const next = property === 'width' ? observed.offsetWidth : observed.offsetHeight
      setSize(next)
      callback?.(next)
    }

    update()
    const observer = new ResizeObserver(() => update())
    try {
      observer.observe(observed)
    } catch (e) {
      console.error('Failed to observe element:', e)
    }

    return () => observer.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetRef.current, target, property])

  return { size }
}
