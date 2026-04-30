import { memo, useMemo } from 'react'
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
}

/**
 * Memoized Markdown renderer. Only re-parses + re-sanitizes when `content`
 * actually changes — important during streaming, where 50 sibling chat
 * bubbles would otherwise each rerun marked+DOMPurify on every chunk.
 */
function MarkdownInner({ content, className }: Props) {
  const html = useMemo(() => {
    if (typeof content !== 'string' || !content) return ''
    const out = marked(content, { renderer }) as string
    return DOMPurify.sanitize(out, { ADD_ATTR: ['target'] })
  }, [content])

  return (
    <div
      className={className}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

const Markdown = memo(MarkdownInner)
export default Markdown
