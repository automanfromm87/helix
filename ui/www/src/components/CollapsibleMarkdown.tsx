import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'

import Markdown from './Markdown'

interface Props {
  content: string
  className?: string
  /** Default-collapse threshold in characters. */
  threshold?: number
  /** Preview length when collapsed. */
  previewChars?: number
}

const DEFAULT_THRESHOLD = 4000
const DEFAULT_PREVIEW = 1500

/**
 * Markdown renderer that defaults to a head-only preview for large content.
 *
 * Long assistant messages (e.g. agent dumping a 50KB README in one go) cost
 * DOM nodes, marked-parse time, and continuous style-recalc weight on every
 * render of the parent list. This wrapper short-circuits that:
 *
 *   - content ≤ threshold  → render the full Markdown subtree as before
 *   - content > threshold  → render `previewChars` of the head plus a
 *     "Show more" toggle. The hidden tail is NOT in the DOM until the user
 *     expands it.
 *
 * On expand, we mount the full content (now larger DOM, but only for the
 * messages the user has explicitly opened — not all of them at once).
 *
 * Memoized at the Markdown layer too, so toggling expand on one message
 * doesn't reparse markdown for siblings.
 */
export default function CollapsibleMarkdown({
  content,
  className,
  threshold = DEFAULT_THRESHOLD,
  previewChars = DEFAULT_PREVIEW,
}: Props) {
  const [expanded, setExpanded] = useState(false)
  const isLong = typeof content === 'string' && content.length > threshold

  if (!isLong) {
    return <Markdown content={content} className={className} />
  }

  // Try to truncate at a paragraph / line boundary for a cleaner preview;
  // fall back to a hard char cut if nothing nearby.
  const cut = expanded ? content.length : findCleanCut(content, previewChars)
  const visible = expanded ? content : content.slice(0, cut)
  const hiddenChars = content.length - cut

  return (
    <div>
      <Markdown content={visible} className={className} />
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="mt-1 inline-flex items-center gap-1 text-xs text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors"
      >
        {expanded ? (
          <>
            <ChevronUp size={12} />
            Show less
          </>
        ) : (
          <>
            <ChevronDown size={12} />
            Show {Math.round(hiddenChars / 1000)}K more chars
          </>
        )}
      </button>
    </div>
  )
}

/**
 * Pick a cut point near `target` that lands on a paragraph break (`\n\n`)
 * if one exists in the window, else a single newline, else just the
 * exact char index. Keeps the preview from chopping mid-sentence.
 */
function findCleanCut(content: string, target: number): number {
  const window = 200
  const minIdx = Math.max(0, target - window)
  const maxIdx = Math.min(content.length, target + window)
  const slice = content.slice(minIdx, maxIdx)
  const para = slice.lastIndexOf('\n\n')
  if (para >= 0) return minIdx + para
  const line = slice.lastIndexOf('\n')
  if (line >= 0) return minIdx + line
  return target
}
