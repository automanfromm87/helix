import { useCallback, useEffect, useRef, useState } from 'react'
import { ExternalLink, MousePointerClick, RefreshCw } from 'lucide-react'

import { apiClient, type ApiResponse } from '@/api/client'
import type { ToolViewProps } from '@/constants/tool'
import * as bus from '@/lib/eventBus'
import { cn } from '@/lib/utils'

/**
 * Live preview of the sandbox dev server, iframed straight from
 * `http://localhost:<host_port>` (docker maps an ephemeral port at
 * sandbox creation, see `DockerSandbox._extract_dev_server_port`).
 *
 * Why this beats the VNC view for "show me the running app":
 * - True browser context — DevTools, real React fast-refresh, the user
 *   can interact with the actual DOM.
 * - No round-trip through x11vnc / websockify, so latency is local-loop.
 * - No Chrome-inside-sandbox compute cost when nobody's debugging headless.
 *
 * The iframe URL is fetched once per session via `GET /sessions/{id}/preview`.
 * It survives sandbox restart (the port mapping is reserved at
 * container-create time) but the dev server might not be up yet — agent
 * has to run `npm run dev -- --host 0.0.0.0` first. While that's
 * pending the iframe shows the browser's default "couldn't connect"
 * page; the Refresh button is one tap away.
 *
 * Inspect mode: parent posts `{source:'helix-parent', type:'inspect:on'}`
 * to the iframe. The user's app must include `src/helix-inspector.ts`
 * (scaffolded by the react-vite-typescript skill); on click it posts
 * back `{source:'helix-inspector', type:'select', payload}`. We turn
 * that into a `helix:preview:select` window event for ChatPage to
 * append to the chat input.
 */
export interface InspectorPayload {
  componentName: string | null
  source: { fileName: string; lineNumber: number; columnNumber?: number } | null
  tagName: string
  className: string
  id: string
  textContent: string
}

export default function PreviewToolView({ sessionId }: ToolViewProps) {
  const [url, setUrl] = useState<string | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const [fetching, setFetching] = useState(false)
  const [inspecting, setInspecting] = useState(false)
  const autoRefetchedRef = useRef(false)
  const iframeRef = useRef<HTMLIFrameElement | null>(null)

  const fetchUrl = useCallback(async () => {
    setFetching(true)
    try {
      const r = await apiClient.get<ApiResponse<{ url: string | null }>>(
        `/sessions/${sessionId}/preview`,
      )
      const newUrl = r.data.data?.url ?? null
      setUrl(newUrl)
      setLoadFailed(false)
    } catch (e) {
      console.error('preview url fetch failed', e)
      setUrl(null)
    } finally {
      setFetching(false)
    }
  }, [sessionId])

  useEffect(() => {
    autoRefetchedRef.current = false
    void fetchUrl()
  }, [fetchUrl])

  // Auto-poll while the dev server is warming up. After fork or initial
  // sandbox creation, the supervisord-managed dev_server runs `pnpm
  // install` first (no node_modules in the bind mount), which takes
  // 30-90s on a cold cache. During that window `getPreviewUrl` returns
  // null because the HEAD probe fails; without a poll the user sees a
  // permanent "No preview yet" and assumes fork failed.
  //
  // Poll every 3s for up to ~3min after mount as long as URL is still
  // null. Stop the moment we get a URL — subsequent re-fetches go
  // through the manual Refresh button or iframe error path.
  useEffect(() => {
    if (url) return  // already up
    let cancelled = false
    let attempts = 0
    const id = window.setInterval(() => {
      attempts++
      if (cancelled || attempts > 60) {
        window.clearInterval(id)
        return
      }
      void fetchUrl()
    }, 3000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [url, fetchUrl])

  const refresh = useCallback(async () => {
    autoRefetchedRef.current = false
    await fetchUrl()
    setReloadKey((k) => k + 1)
  }, [fetchUrl])

  const handleIframeError = useCallback(() => {
    setLoadFailed(true)
    if (!autoRefetchedRef.current) {
      autoRefetchedRef.current = true
      void fetchUrl()
    }
  }, [fetchUrl])

  const postToIframe = useCallback((msg: Record<string, unknown>) => {
    iframeRef.current?.contentWindow?.postMessage({ source: 'helix-parent', ...msg }, '*')
  }, [])

  const toggleInspect = useCallback(() => {
    setInspecting((prev) => {
      const next = !prev
      postToIframe({ type: next ? 'inspect:on' : 'inspect:off' })
      return next
    })
  }, [postToIframe])

  // Receive messages from the inspector helper running inside the iframe.
  // Wide listener (any origin) is fine — we filter strictly on the
  // {source:'helix-inspector'} marker plus message shape.
  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      const d = e.data
      if (!d || d.source !== 'helix-inspector') return
      if (d.type === 'select') {
        bus.emit('helix:preview:select', d.payload as InspectorPayload)
        setInspecting(false)
      } else if (d.type === 'cancel') {
        setInspecting(false)
      }
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [])

  const iframeSrc = url ? `${url}?_helix_r=${reloadKey}` : ''

  return (
    <div className="flex flex-col h-full w-full">
      <div className="h-[36px] flex items-center gap-2 px-3 w-full bg-[var(--background-gray-main)] border-b border-[var(--border-main)] rounded-t-[12px] shadow-[inset_0px_1px_0px_0px_#FFFFFF] dark:shadow-[inset_0px_1px_0px_0px_#FFFFFF30] flex-shrink-0">
        <div className="flex-1 flex items-center gap-2 min-w-0">
          <span
            className={cn(
              'w-2 h-2 rounded-full flex-shrink-0',
              loadFailed
                ? 'bg-[var(--function-error)]'
                : url
                  ? 'bg-[var(--function-success)]'
                  : 'bg-[var(--icon-tertiary)]',
            )}
            aria-hidden
          />
          <div
            className="text-[var(--text-secondary)] text-sm font-medium truncate"
            title={url ?? undefined}
          >
            {url
              ? loadFailed
                ? 'Connection failed'
                : 'Sandbox running'
              : 'Setting up dev server…'}
          </div>
        </div>
        {url && (
          <>
            <button
              type="button"
              onClick={toggleInspect}
              title={inspecting ? 'Exit inspect mode' : 'Inspect element (writes source info to chat)'}
              className={cn(
                'h-6 w-6 inline-flex items-center justify-center rounded-md',
                inspecting
                  ? 'bg-[var(--text-brand)] text-white'
                  : 'hover:bg-[var(--fill-tsp-white-light)] text-[var(--icon-secondary)]',
              )}
            >
              <MousePointerClick size={14} />
            </button>
            <button
              type="button"
              onClick={refresh}
              title="Reload preview"
              className="h-6 w-6 inline-flex items-center justify-center rounded-md hover:bg-[var(--fill-tsp-white-light)] text-[var(--icon-secondary)]"
            >
              <RefreshCw size={14} />
            </button>
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              title="Open in new tab"
              className="h-6 w-6 inline-flex items-center justify-center rounded-md hover:bg-[var(--fill-tsp-white-light)] text-[var(--icon-secondary)]"
            >
              <ExternalLink size={14} />
            </a>
          </>
        )}
      </div>
      <div className="flex-1 min-h-0 bg-white dark:bg-black relative">
        {url ? (
          <iframe
            key={reloadKey}
            ref={iframeRef}
            src={iframeSrc}
            title="Sandbox preview"
            className="absolute inset-0 w-full h-full border-0"
            // `sandbox` flags gate iframe security (forms, popups for OAuth,
            // same-origin for React dev tools). Clipboard isn't a sandbox
            // flag — it's a Permissions Policy on `allow=`, hence the split.
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
            allow="clipboard-read; clipboard-write"
            onLoad={() => setLoadFailed(false)}
            onError={handleIframeError}
          />
        ) : (
          <div className="h-full flex flex-col items-center justify-center px-6 text-center gap-3">
            <div className="size-3 rounded-full bg-[var(--icon-tertiary)] opacity-60 animate-pulse" />
            <div className="text-[var(--text-secondary)] text-sm font-medium">
              Setting up dev server…
            </div>
            <div className="text-[var(--text-tertiary)] text-xs max-w-[320px] leading-snug">
              Installing dependencies and starting Vite. Usually 30-60 seconds
              on first launch; the iframe will fill in automatically.
            </div>
          </div>
        )}
        {loadFailed && url && (
          <div className="absolute inset-0 flex items-center justify-center bg-[var(--background-gray-main)]/95">
            <div className="text-center px-6">
              <div className="text-[var(--text-primary)] text-sm font-medium mb-1">
                Could not connect to {url}
              </div>
              <div className="text-[var(--text-tertiary)] text-xs">
                The dev server may not be running yet. Once the agent
                runs <code className="font-mono">npm run dev</code>, hit
                Refresh.
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
