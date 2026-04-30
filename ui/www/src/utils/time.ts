/** Convert ISO 8601 to unix seconds. */
export const parseISODateTime = (isoString: string): number => {
  const date = new Date(isoString)
  if (isNaN(date.getTime())) {
    throw new Error(`Failed to parse ISO datetime string: ${isoString}`)
  }
  return Math.floor(date.getTime() / 1000)
}

/** Relative time formatter: now / minutes / hours / days / months / years ago. */
export const formatRelativeTime = (timestamp: number): string => {
  const now = Math.floor(Date.now() / 1000)
  const diffSec = now - timestamp
  const diffMin = Math.floor(diffSec / 60)
  const diffHour = Math.floor(diffMin / 60)
  const diffDay = Math.floor(diffHour / 24)
  const diffMonth = Math.floor(diffDay / 30)
  const diffYear = Math.floor(diffMonth / 12)

  const fmt = (n: number, unit: string) => `${n} ${unit}${n === 1 ? '' : 's'} ago`

  if (diffSec < 60) return 'Just now'
  if (diffMin < 60) return fmt(diffMin, 'minute')
  if (diffHour < 24) return fmt(diffHour, 'hour')
  if (diffDay < 30) return fmt(diffDay, 'day')
  if (diffMonth < 12) return fmt(diffMonth, 'month')
  return fmt(diffYear, 'year')
}

/** Custom time formatter for sidebar session list. */
export const formatCustomTime = (timestamp: number): string => {
  const date = new Date(timestamp * 1000)
  const now = new Date()

  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })
  }

  const startOfWeek = new Date(now)
  startOfWeek.setDate(now.getDate() - now.getDay() + 1)
  startOfWeek.setHours(0, 0, 0, 0)
  const endOfWeek = new Date(startOfWeek)
  endOfWeek.setDate(startOfWeek.getDate() + 6)
  endOfWeek.setHours(23, 59, 59, 999)

  if (date >= startOfWeek && date <= endOfWeek) {
    const weekdays = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    return weekdays[date.getDay()]
  }

  if (date.getFullYear() === now.getFullYear()) {
    return `${String(date.getMonth() + 1).padStart(2, '0')}/${String(date.getDate()).padStart(2, '0')}`
  }
  return `${date.getFullYear()}/${String(date.getMonth() + 1).padStart(2, '0')}`
}
