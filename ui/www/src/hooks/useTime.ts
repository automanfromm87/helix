import { useEffect, useState } from 'react'
import { formatCustomTime, formatRelativeTime } from '@/utils/time'

/** Tick a state every minute so relative-time labels rerender without explicit deps. */
function useMinuteTick() {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 60_000)
    return () => window.clearInterval(id)
  }, [])
  return now
}

export function useRelativeTime() {
  const tick = useMinuteTick()
  return {
    relativeTime: (timestamp: number) => {
      void tick
      return formatRelativeTime(timestamp)
    },
  }
}

export function useCustomTime() {
  const tick = useMinuteTick()
  return {
    customTime: (timestamp: number) => {
      void tick
      return formatCustomTime(timestamp)
    },
  }
}
