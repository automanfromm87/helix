import { memo, useDeferredValue, useMemo } from 'react'
import DOMPurify from 'dompurify'
import { marked } from 'marked'

const renderer = new marked.Renderer()
const originalLink = renderer.link?.bind(renderer)
renderer.link = (token: any) => {
  const href = token?.href ?? token
  const title = token?.title ?? null
  const text = token?.text ?? ''
  const titleAttr = title ? ` title="${title}"` : ''
  if (typeof href === 'string') {
    return `<a href="${href}" target="_blank" rel="noopener noreferrer"${titleAttr}>${text}</a>`
  }
  return originalLink ? originalLink(token) : ''
}

interface Props {
  content: string
  className?: string
  /**
   * When true, signals this is a streaming partial — Markdown defers the
   * marked+sanitize work via `useDeferredValue` so React can coalesce many
   * incoming chunks into a single low-priority render. Once the producer
   * flips to false (final chunk) the parse runs urgently and the bubble
   * settles to its committed shape.
   *
   * Without this, every ~300 chars of streamed text triggers a full
   * marked.parse + DOMPurify.sanitize + DOM teardown cycle — feels janky
   * on a long answer.
   */
  partial?: boolean
}

/**
 * Memoized Markdown renderer. Only re-parses + re-sanitizes when `content`
 * actually changes — important during streaming, where 50 sibling chat
 * bubbles would otherwise each rerun marked+DOMPurify on every chunk.
 */
function MarkdownInner({ content, className, partial }: Props) {
  // For streaming partials, useDeferredValue lets React skip intermediate
  // values when the next chunk arrives before the prior render commits.
  // For final / non-partial content, deferredContent === content so the
  // render path is identical to the pre-streaming-aware version.
  const deferredContent = useDeferredValue(content)
  const sourceContent = partial ? deferredContent : content

  const html = useMemo(() => {
    if (typeof sourceContent !== 'string' || !sourceContent) return ''
    const out = marked(sourceContent, { renderer }) as string
    return DOMPurify.sanitize(out, { ADD_ATTR: ['target'] })
  }, [sourceContent])

  return (
    <div
      className={className}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

const Markdown = memo(MarkdownInner)
export default Markdown
