import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowLeft, Check, ExternalLink, Loader2, RefreshCw, X } from 'lucide-react'

import { apiClient, type ApiResponse } from '@/api/client'
import { deleteSession } from '@/api/agent'
import { showErrorToast, showSuccessToast } from '@/utils/toast'
import { cn } from '@/lib/utils'

interface VariantState {
  sessionId: string
  label: string
  url: string | null
  fetching: boolean
  loadFailed: boolean
  reloadKey: number
}

/**
 * Side-by-side preview comparison for a multi-fork group.
 *
 * URL contract: `/compare?sessions=a,b,c&labels=base64a,base64b,base64c`.
 * Labels are base64 to safely round-trip arbitrary user input through
 * the URL bar (commas, &, /, etc.). Falls back to "Variant N" when a
 * label is missing.
 *
 * Each tile is its own preview iframe + "Keep" button. "Keep" deletes
 * the other variants' sessions (which cascades sandbox + bind-mount
 * cleanup) and navigates to the kept session's chat page. The whole
 * decision is one click — that's the demo's "fork is cheap, throw it
 * away when you're done" point.
 */
export default function ComparePage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()

  const variants = useMemo<VariantState[]>(() => {
    const ids = (params.get('sessions') ?? '').split(',').filter(Boolean)
    const labels = (params.get('labels') ?? '').split(',')
    return ids.map((id, i) => ({
      sessionId: id,
      label: decodeLabel(labels[i]) || `Variant ${i + 1}`,
      url: null,
      fetching: false,
      loadFailed: false,
      reloadKey: 0,
    }))
  }, [params])

  const [state, setState] = useState<VariantState[]>(variants)

  // Re-seed when the URL changes (rare — the user shouldn't be hand-
  // editing this URL — but the search-params hook returns a new object
  // on every render so memoizing the derived array is the simpler path
  // than wiring a custom hook).
  useEffect(() => {
    setState(variants)
  }, [variants])

  const fetchUrl = useCallback(async (idx: number) => {
    const sessionId = state[idx]?.sessionId
    if (!sessionId) return
    setState((prev) =>
      prev.map((v, i) => (i === idx ? { ...v, fetching: true } : v)),
    )
    try {
      const r = await apiClient.get<ApiResponse<{ url: string | null }>>(
        `/sessions/${sessionId}/preview`,
      )
      const url = r.data.data?.url ?? null
      setState((prev) =>
        prev.map((v, i) =>
          i === idx ? { ...v, url, fetching: false, loadFailed: false } : v,
        ),
      )
    } catch {
      setState((prev) =>
        prev.map((v, i) => (i === idx ? { ...v, fetching: false } : v)),
      )
    }
  }, [state])

  // Initial fetch + slow auto-poll while any URL is still null. Forks
  // need 30-90s for pnpm install + vite cold start; this same pattern
  // lives in PreviewToolView for single-session preview.
  useEffect(() => {
    state.forEach((v, i) => {
      if (!v.url && !v.fetching) void fetchUrl(i)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [variants])

  useEffect(() => {
    const id = window.setInterval(() => {
      state.forEach((v, i) => {
        if (!v.url && !v.fetching) void fetchUrl(i)
      })
    }, 3000)
    return () => window.clearInterval(id)
  }, [state, fetchUrl])

  const onReload = (idx: number) => {
    setState((prev) =>
      prev.map((v, i) =>
        i === idx ? { ...v, reloadKey: v.reloadKey + 1, loadFailed: false } : v,
      ),
    )
  }

  const onKeep = async (keepIdx: number) => {
    const keep = state[keepIdx]
    if (!keep) return
    const losers = state.filter((_, i) => i !== keepIdx)
    if (
      !window.confirm(
        `Keep "${keep.label}" and discard the other ${losers.length} variant${
          losers.length === 1 ? '' : 's'
        }? This deletes the discarded sessions.`,
      )
    ) return

    // Sequential delete — each deleteSession blows away its sandbox and
    // bind-mount; running them in parallel risks docker daemon storm
    // and isn't user-perceptibly faster.
    for (const v of losers) {
      try {
        await deleteSession(v.sessionId)
      } catch (e) {
        // Swallow — losing a variant cleanup shouldn't block the user
        // from moving on. The orphan reaper will sweep it eventually.
        console.error('discard failed', v.sessionId, e)
      }
    }
    showSuccessToast('Kept variant')
    navigate(`/chat/${keep.sessionId}`)
  }

  const onDiscardAll = async () => {
    if (
      !window.confirm(
        `Discard all ${state.length} variants? This deletes every session in this comparison.`,
      )
    ) return
    for (const v of state) {
      try {
        await deleteSession(v.sessionId)
      } catch (e) {
        console.error('discard failed', v.sessionId, e)
        showErrorToast(`Failed to delete ${v.label}`)
      }
    }
    navigate('/')
  }

  if (state.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-8 text-center gap-3 text-[var(--text-tertiary)]">
        <div>No variants in this comparison.</div>
        <Link to="/" className="text-sm text-[var(--text-brand)]">
          Back home
        </Link>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-[var(--background-gray-main)]">
      <header className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-light)] flex-shrink-0">
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="inline-flex items-center gap-1.5 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
        >
          <ArrowLeft size={16} />
          Back
        </button>
        <div className="text-[var(--text-primary)] font-medium">
          Compare variants
          <span className="ms-2 text-[var(--text-tertiary)] tabular-nums text-sm font-normal">
            {state.length}
          </span>
        </div>
        <button
          type="button"
          onClick={onDiscardAll}
          className="inline-flex items-center gap-1 text-sm text-[var(--function-error)] hover:underline"
        >
          <X size={14} />
          Discard all
        </button>
      </header>

      <div
        className="flex-1 grid gap-3 p-3 min-h-0"
        style={{
          gridTemplateColumns: `repeat(${state.length}, minmax(0, 1fr))`,
        }}
      >
        {state.map((v, i) => (
          <VariantTile
            key={v.sessionId}
            variant={v}
            onReload={() => onReload(i)}
            onKeep={() => onKeep(i)}
            onIframeError={() =>
              setState((prev) =>
                prev.map((s, idx) => (idx === i ? { ...s, loadFailed: true } : s)),
              )
            }
            onIframeLoad={() =>
              setState((prev) =>
                prev.map((s, idx) => (idx === i ? { ...s, loadFailed: false } : s)),
              )
            }
          />
        ))}
      </div>
    </div>
  )
}

interface TileProps {
  variant: VariantState
  onReload: () => void
  onKeep: () => void
  onIframeError: () => void
  onIframeLoad: () => void
}

function VariantTile({
  variant,
  onReload,
  onKeep,
  onIframeError,
  onIframeLoad,
}: TileProps) {
  const navigate = useNavigate()
  const iframeSrc = variant.url
    ? `${variant.url}?_helix_r=${variant.reloadKey}`
    : ''

  return (
    <div className="flex flex-col h-full min-w-0 rounded-md border border-[var(--border-light)] bg-white dark:bg-black overflow-hidden">
      <div className="flex items-center justify-between gap-2 px-3 py-2 bg-[var(--background-gray-main)] border-b border-[var(--border-light)]">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className={cn(
              'w-2 h-2 rounded-full flex-shrink-0',
              variant.loadFailed
                ? 'bg-[var(--function-error)]'
                : variant.url
                  ? 'bg-[var(--function-success)]'
                  : 'bg-[var(--icon-tertiary)]',
            )}
            aria-hidden
          />
          <span
            className="text-sm font-medium text-[var(--text-primary)] truncate"
            title={variant.label}
          >
            {variant.label}
          </span>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          <button
            type="button"
            onClick={() => navigate(`/chat/${variant.sessionId}`)}
            title="Open chat"
            className="h-7 w-7 inline-flex items-center justify-center rounded-md hover:bg-[var(--fill-tsp-white-light)] text-[var(--icon-secondary)]"
          >
            <ExternalLink size={14} />
          </button>
          <button
            type="button"
            onClick={onReload}
            title="Reload preview"
            disabled={!variant.url}
            className="h-7 w-7 inline-flex items-center justify-center rounded-md hover:bg-[var(--fill-tsp-white-light)] text-[var(--icon-secondary)] disabled:opacity-40"
          >
            <RefreshCw size={14} />
          </button>
          <button
            type="button"
            onClick={onKeep}
            className="h-7 px-3 inline-flex items-center gap-1 rounded-md text-sm font-medium bg-[var(--text-brand)] text-white hover:opacity-90"
          >
            <Check size={14} />
            Keep
          </button>
        </div>
      </div>
      <div className="flex-1 relative min-h-0">
        {variant.url ? (
          <iframe
            key={variant.reloadKey}
            src={iframeSrc}
            title={variant.label}
            className="absolute inset-0 w-full h-full border-0"
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
            onLoad={onIframeLoad}
            onError={onIframeError}
          />
        ) : (
          <div className="h-full flex flex-col items-center justify-center px-4 text-center gap-3">
            <Loader2 size={20} className="text-[var(--icon-tertiary)] animate-spin" />
            <div className="text-sm text-[var(--text-secondary)]">
              Spinning up dev server…
            </div>
            <div className="text-xs text-[var(--text-tertiary)] max-w-[260px] leading-snug">
              The first run does a fresh <code className="font-mono">pnpm install</code>;
              this can take 30-90s.
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function decodeLabel(b64?: string): string {
  if (!b64) return ''
  try {
    return decodeURIComponent(escape(atob(b64)))
  } catch {
    return ''
  }
}
