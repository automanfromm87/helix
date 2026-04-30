import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search } from 'lucide-react'

import { searchSessions } from '@/api/agent'
import { useCommandPalette } from '@/hooks/useCommandPalette'
import { Dialog, DialogContent } from './ui/Dialog'
import type { ListSessionItem } from '@/types/response'
import { cn } from '@/lib/utils'

const DEBOUNCE_MS = 200

export default function CommandPalette() {
  const navigate = useNavigate()
  const visible = useCommandPalette((s) => s.visible)
  const close = useCommandPalette((s) => s.close)
  const inputRef = useRef<HTMLInputElement>(null)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<ListSessionItem[]>([])
  const [activeIdx, setActiveIdx] = useState(0)
  const [loading, setLoading] = useState(false)

  // Reset every time the palette is opened.
  useEffect(() => {
    if (!visible) return
    setQuery('')
    setResults([])
    setActiveIdx(0)
    requestAnimationFrame(() => inputRef.current?.focus())
  }, [visible])

  // Debounced search.
  useEffect(() => {
    if (!visible) return
    if (!query.trim()) {
      setResults([])
      setLoading(false)
      return
    }
    setLoading(true)
    const handle = window.setTimeout(async () => {
      try {
        const res = await searchSessions(query)
        setResults(res.sessions)
        setActiveIdx(0)
      } catch (e) {
        console.error('Search failed:', e)
        setResults([])
      } finally {
        setLoading(false)
      }
    }, DEBOUNCE_MS)
    return () => window.clearTimeout(handle)
  }, [query, visible])

  const choose = (s: ListSessionItem) => {
    close()
    navigate(`/chat/${s.session_id}`)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx((i) => Math.min(i + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const target = results[activeIdx]
      if (target) choose(target)
    }
  }

  return (
    <Dialog open={visible} onOpenChange={(open) => (open ? null : close())}>
      <DialogContent className="max-w-xl p-0 gap-0" showCloseButton={false}>
        <div className="flex items-center gap-2 px-4 py-3 border-b border-[var(--border-light)]">
          <Search size={16} className="text-[var(--icon-tertiary)]" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search sessions by title, message, or tool output…"
            className="flex-1 bg-transparent outline-none text-sm placeholder-[var(--text-tertiary)]"
          />
        </div>
        <div className="max-h-[400px] overflow-y-auto">
          {loading && (
            <div className="px-4 py-3 text-sm text-[var(--text-tertiary)]">Searching…</div>
          )}
          {!loading && query.trim() && results.length === 0 && (
            <div className="px-4 py-3 text-sm text-[var(--text-tertiary)]">No matches.</div>
          )}
          {results.map((s, i) => (
            <button
              key={s.session_id}
              onClick={() => choose(s)}
              onMouseEnter={() => setActiveIdx(i)}
              className={cn(
                'w-full text-left px-4 py-2 flex flex-col gap-0.5',
                i === activeIdx
                  ? 'bg-[var(--fill-tsp-white-main)]'
                  : 'hover:bg-[var(--fill-tsp-white-light)]',
              )}
            >
              <div className="text-sm text-[var(--text-primary)] truncate">
                {s.title || 'New Chat'}
              </div>
              {s.latest_message && (
                <div className="text-xs text-[var(--text-tertiary)] truncate">
                  {s.latest_message}
                </div>
              )}
            </button>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
