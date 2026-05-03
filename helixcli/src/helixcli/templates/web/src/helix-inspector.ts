// Helix preview inspector — dev-only. Loaded conditionally from
// main.tsx; the production build never imports it.
//
// Reads `_debugSource` off React fibers (set by the JSX dev transform
// in @vitejs/plugin-react) and posts the click target's component +
// source location to the parent helix UI.

interface SourceLoc {
  fileName: string
  lineNumber: number
  columnNumber?: number
}

declare global {
  interface Window {
    __HELIX_INSPECTOR__?: boolean
  }
}

if (!window.__HELIX_INSPECTOR__) {
  window.__HELIX_INSPECTOR__ = true

  let active = false
  let overlay: HTMLDivElement | null = null
  let label: HTMLDivElement | null = null

  const ensureOverlay = () => {
    if (overlay) return overlay
    overlay = document.createElement('div')
    Object.assign(overlay.style, {
      position: 'fixed',
      pointerEvents: 'none',
      zIndex: '2147483647',
      border: '2px solid #2563eb',
      background: 'rgba(37, 99, 235, 0.08)',
      borderRadius: '2px',
      transition: 'all 50ms ease-out',
      display: 'none',
    })
    label = document.createElement('div')
    Object.assign(label.style, {
      position: 'absolute',
      top: '-22px',
      left: '0',
      padding: '2px 6px',
      borderRadius: '4px',
      background: '#2563eb',
      color: '#fff',
      font: '11px ui-monospace, SFMono-Regular, monospace',
      whiteSpace: 'nowrap',
      pointerEvents: 'none',
    })
    overlay.appendChild(label)
    document.body.appendChild(overlay)
    return overlay
  }

  const moveOverlay = (el: Element, name: string) => {
    const r = el.getBoundingClientRect()
    const o = ensureOverlay()
    o.style.display = 'block'
    o.style.top = r.top + 'px'
    o.style.left = r.left + 'px'
    o.style.width = r.width + 'px'
    o.style.height = r.height + 'px'
    if (label) label.textContent = name
  }

  const hideOverlay = () => {
    if (overlay) overlay.style.display = 'none'
  }

  const fiberOf = (el: Element): any => {
    const k = Object.keys(el).find(
      (s) => s.startsWith('__reactFiber$') || s.startsWith('__reactInternalInstance$'),
    )
    return k ? (el as any)[k] : null
  }

  // React 18 stored source on `fiber._debugSource = {fileName,lineNumber}`.
  // React 19 removed that field and instead stashes an `Error` at element
  // creation on `fiber._debugStack`; the first non-React frame in its
  // stack is the JSX call site. We try the old field first (any older
  // project still works), then parse the new one.
  const parseStack = (err: any): SourceLoc | null => {
    if (!err || typeof err.stack !== 'string') return null
    for (const raw of err.stack.split('\n')) {
      const line = raw.trim()
      if (!line || /^Error\b/.test(line)) continue
      if (/\/(react|react-dom|react\/jsx-(dev-)?runtime)/.test(line)) continue
      const m =
        line.match(/\bat\s+(?:[^(]*\()?(.+?):(\d+):(\d+)\)?$/) ||
        line.match(/@(.+?):(\d+):(\d+)$/)
      if (!m) continue
      const url = m[1].split('?')[0].replace(/^https?:\/\/[^/]+/, '').replace(/^\/+/, '')
      return {
        fileName: url,
        lineNumber: parseInt(m[2], 10),
        columnNumber: parseInt(m[3], 10),
      }
    }
    return null
  }

  const sourceOf = (fiber: any): SourceLoc | null => {
    if (!fiber) return null
    if (fiber._debugSource) return fiber._debugSource as SourceLoc
    return parseStack(fiber._debugStack)
  }

  const ownerOf = (fiber: any): { name: string | null; source: SourceLoc | null } => {
    let f = fiber?.return
    while (f) {
      if (typeof f.type === 'function') {
        return {
          name: f.type.displayName || f.type.name || 'Anonymous',
          source: sourceOf(f),
        }
      }
      f = f.return
    }
    return { name: null, source: null }
  }

  const readPayload = (el: Element) => {
    const fiber = fiberOf(el)
    const owner = ownerOf(fiber)
    const cls = (el as HTMLElement).className
    return {
      componentName: owner.name,
      source: sourceOf(fiber) ?? owner.source ?? null,
      tagName: el.tagName.toLowerCase(),
      className: typeof cls === 'string' ? cls : (cls as any)?.toString?.() ?? '',
      id: (el as HTMLElement).id ?? '',
      textContent: (el.textContent ?? '').slice(0, 200).trim(),
    }
  }

  const post = (msg: Record<string, unknown>) => {
    if (window.parent !== window) {
      window.parent.postMessage({ source: 'helix-inspector', ...msg }, '*')
    }
  }

  const onMove = (e: MouseEvent) => {
    const t = e.target as Element | null
    if (!t || t === overlay || (overlay && overlay.contains(t))) return
    const fiber = fiberOf(t)
    const owner = ownerOf(fiber)
    moveOverlay(t, owner.name ?? t.tagName.toLowerCase())
  }

  const onClick = (e: MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const t = e.target as Element | null
    if (!t) return
    post({ type: 'select', payload: readPayload(t) })
    deactivate()
  }

  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      post({ type: 'cancel' })
      deactivate()
    }
  }

  const activate = () => {
    if (active) return
    active = true
    document.addEventListener('mousemove', onMove, true)
    document.addEventListener('click', onClick, true)
    document.addEventListener('keydown', onKey, true)
    document.body.style.cursor = 'crosshair'
  }

  const deactivate = () => {
    if (!active) return
    active = false
    hideOverlay()
    document.removeEventListener('mousemove', onMove, true)
    document.removeEventListener('click', onClick, true)
    document.removeEventListener('keydown', onKey, true)
    document.body.style.cursor = ''
  }

  window.addEventListener('message', (e: MessageEvent) => {
    const d = e.data
    if (!d || d.source !== 'helix-parent') return
    if (d.type === 'inspect:on') activate()
    else if (d.type === 'inspect:off') deactivate()
  })

  post({ type: 'ready' })
}

export {}
