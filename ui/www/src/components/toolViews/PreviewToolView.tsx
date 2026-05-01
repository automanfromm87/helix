import { useCallback, useEffect, useRef, useState } from 'react'
import { ExternalLink, RefreshCw } from 'lucide-react'

import { apiClient, type ApiResponse } from '@/api/client'
import type { ToolViewProps } from '@/constants/tool'

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
 */
export default function PreviewToolView({ sessionId }: ToolViewProps) {
  const [url, setUrl] = useState<string | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)
  // Bumped on Refresh to force the iframe to reload — appended as a
  // cache-buster query param so dev-server SPAs don't serve stale HTML.
  const [reloadKey, setReloadKey] = useState(0)
  const [fetching, setFetching] = useState(false)
  // Track whether we've already auto-refetched after a load error this
  // mount, so we don't spin (the error event can fire multiple times).
  const autoRefetchedRef = useRef(false)

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

  // Refresh: re-fetch the preview URL AND bump the iframe reload key.
  // The URL re-fetch handles the case where the sandbox got replaced
  // (backend restart / TTL eviction) — its host port changes between
  // sandbox lifetimes, so just reloading the old URL would still hit
  // a dead port. We always re-fetch first, then bump the key after the
  // URL state lands.
  const refresh = useCallback(async () => {
    autoRefetchedRef.current = false
    await fetchUrl()
    setReloadKey((k) => k + 1)
  }, [fetchUrl])

  // When the iframe fails to load (e.g. dev server not yet up, port
  // changed after sandbox replacement), do ONE silent re-fetch of the
  // URL. If the new URL works the iframe reloads on the next render;
  // if it still fails, surface the manual Refresh banner.
  const handleIframeError = useCallback(() => {
    setLoadFailed(true)
    if (!autoRefetchedRef.current) {
      autoRefetchedRef.current = true
      void fetchUrl()
    }
  }, [fetchUrl])

  const iframeSrc = url ? `${url}?_helix_r=${reloadKey}` : ''

  return (
    <div className="flex flex-col h-full w-full">
      <div className="h-[36px] flex items-center gap-2 px-3 w-full bg-[var(--background-gray-main)] border-b border-[var(--border-main)] rounded-t-[12px] shadow-[inset_0px_1px_0px_0px_#FFFFFF] dark:shadow-[inset_0px_1px_0px_0px_#FFFFFF30] flex-shrink-0">
        <div className="flex-1 flex items-center min-w-0">
          <div className="text-[var(--text-tertiary)] text-sm font-medium truncate font-mono">
            {url || (fetching ? 'Loading preview…' : 'No preview available')}
          </div>
        </div>
        {url && (
          <>
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
            src={iframeSrc}
            title="Sandbox preview"
            className="absolute inset-0 w-full h-full border-0"
            // `allow-*` opens the gate for normal SPA features (forms,
            // popups for OAuth flows, clipboard for copy buttons).
            // `allow-same-origin` is required for many React dev-tools.
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-clipboard-read allow-clipboard-write allow-modals"
            onLoad={() => setLoadFailed(false)}
            onError={handleIframeError}
          />
        ) : (
          <div className="h-full flex items-center justify-center px-6 text-center">
            <div className="text-[var(--text-tertiary)] text-sm">
              {fetching
                ? 'Resolving preview URL…'
                : 'No preview port has been allocated for this session yet. Send a message to provision the sandbox.'}
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
