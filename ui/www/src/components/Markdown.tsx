import { memo, useDeferredValue, useEffect, useMemo, useRef } from 'react'
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

// Wrap fenced code blocks in a header strip showing the language and a
// hover-to-show Copy button. Click handling is wired up in MarkdownInner via
// event delegation since the body is dropped in via dangerouslySetInnerHTML.
const escapeHtml = (s: string) =>
  s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')

renderer.code = (tokenOrText: any, maybeLang?: string, maybeEscaped?: boolean) => {
  const text: string =
    typeof tokenOrText === 'string' ? tokenOrText : (tokenOrText?.text ?? '')
  const lang: string | undefined =
    typeof tokenOrText === 'string' ? maybeLang : tokenOrText?.lang
  const escaped: boolean =
    typeof tokenOrText === 'string'
      ? Boolean(maybeEscaped)
      : Boolean(tokenOrText?.escaped)
  const body = escaped ? text : escapeHtml(text)
  const langLabel = (lang || '').trim() || 'text'
  const langClass = lang ? ` class="language-${escapeHtml(lang)}"` : ''
  return (
    `<div class="helix-code" data-lang="${escapeHtml(langLabel)}">` +
    `<div class="helix-code-header">` +
    `<span class="helix-code-lang">${escapeHtml(langLabel)}</span>` +
    `<button type="button" class="helix-code-copy" aria-label="Copy code">Copy</button>` +
    `</div>` +
    `<pre><code${langClass}>${body}</code></pre>` +
    `</div>`
  )
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
   */
  partial?: boolean
}

/**
 * Memoized Markdown renderer. Only re-parses + re-sanitizes when `content`
 * actually changes — important during streaming, where 50 sibling chat
 * bubbles would otherwise each rerun marked+DOMPurify on every chunk.
 */
function MarkdownInner({ content, className, partial }: Props) {
  const deferredContent = useDeferredValue(content)
  const sourceContent = partial ? deferredContent : content
  const containerRef = useRef<HTMLDivElement | null>(null)

  const html = useMemo(() => {
    if (typeof sourceContent !== 'string' || !sourceContent) return ''
    const out = marked(sourceContent, { renderer }) as string
    return DOMPurify.sanitize(out, { ADD_ATTR: ['target'] })
  }, [sourceContent])

  // Single delegated listener for all code-block copy buttons. Re-binding
  // per render is cheap (one addEventListener) and avoids tracking per-button
  // wiring after each marked re-parse.
  useEffect(() => {
    const root = containerRef.current
    if (!root) return
    const onClick = (e: Event) => {
      const btn = (e.target as Element | null)?.closest('.helix-code-copy')
      if (!btn) return
      const block = btn.closest('.helix-code')
      const code = block?.querySelector('pre code')?.textContent ?? ''
      if (!code) return
      void navigator.clipboard.writeText(code).then(() => {
        btn.setAttribute('data-state', 'copied')
        btn.textContent = 'Copied'
        window.setTimeout(() => {
          btn.removeAttribute('data-state')
          btn.textContent = 'Copy'
        }, 1500)
      })
    }
    root.addEventListener('click', onClick)
    return () => root.removeEventListener('click', onClick)
  }, [html])

  return (
    <div
      ref={containerRef}
      className={className}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

const Markdown = memo(MarkdownInner)
export default Markdown
