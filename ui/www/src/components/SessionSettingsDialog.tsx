import { useCallback, useEffect, useRef, useState } from 'react'
import { FileText, Globe, Loader2, Plus, Trash2, Upload, Wrench } from 'lucide-react'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from './ui/Dialog'
import {
  deleteContextFile,
  getSessionSettings,
  listContextFiles,
  setRetrievalMode,
  uploadContextFile,
  uploadContextFileFromUrl,
  type ContextFileSummary,
} from '@/api/agent'
import { showErrorToast, showSuccessToast } from '@/utils/toast'
import { cn } from '@/lib/utils'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  sessionId: string
}

const ACCEPT = '.md,.markdown,.txt,text/markdown,text/plain'

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function errMsg(e: unknown): string {
  return (
    (e as { message?: string; msg?: string })?.message ??
    (e as { msg?: string })?.msg ??
    String(e)
  )
}

/**
 * Per-session config dialog. Two real sections so far:
 *
 *   - Context files: Markdown attachments. Upload via picker OR paste a
 *     URL (server fetches + html→md). Server enforces caps (256 KB per
 *     file, 20 files, 2 MB total). Failed validations surface as toasts.
 *   - Tools / Retrieval mode: a single toggle today — when on, attached
 *     files are reached only via `retrieve(query)` instead of being
 *     dumped into the prompt. Worth it once the corpus dwarfs the
 *     per-turn token budget.
 */
export default function SessionSettingsDialog({
  open,
  onOpenChange,
  sessionId,
}: Props) {
  const [files, setFiles] = useState<ContextFileSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set())
  const [urlValue, setUrlValue] = useState('')
  const [urlBusy, setUrlBusy] = useState(false)
  const [retrievalOnly, setRetrievalOnly] = useState(false)
  const [retrievalSaving, setRetrievalSaving] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [list, settings] = await Promise.all([
        listContextFiles(sessionId),
        getSessionSettings(sessionId).catch(() => null),
      ])
      setFiles(list)
      if (settings) setRetrievalOnly(settings.retrieval_only_context)
    } catch (e) {
      console.error('load session settings failed', e)
    } finally {
      setLoading(false)
    }
  }, [sessionId])

  useEffect(() => {
    if (open) void refresh()
  }, [open, refresh])

  const onPick = () => fileInputRef.current?.click()

  const onFiles = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(e.target.files ?? [])
    e.target.value = ''
    if (picked.length === 0) return
    setUploading(true)
    try {
      // Sequential — keeps server-side count/total caps deterministic
      // across the batch. Parallel uploads could each individually pass
      // the per-file check yet collectively exceed total, leaving
      // partial state.
      for (const f of picked) {
        const text = await f.text()
        try {
          await uploadContextFile(sessionId, f.name, text)
        } catch (err) {
          showErrorToast(`${f.name}: ${errMsg(err)}`)
        }
      }
      await refresh()
    } finally {
      setUploading(false)
    }
  }

  const onAddUrl = async () => {
    const url = urlValue.trim()
    if (!url) return
    setUrlBusy(true)
    try {
      await uploadContextFileFromUrl(sessionId, url)
      setUrlValue('')
      await refresh()
      showSuccessToast('Added')
    } catch (e) {
      showErrorToast(`URL: ${errMsg(e)}`)
    } finally {
      setUrlBusy(false)
    }
  }

  const onDelete = async (id: string) => {
    setBusyIds((s) => new Set(s).add(id))
    try {
      await deleteContextFile(sessionId, id)
      setFiles((prev) => prev.filter((f) => f.id !== id))
      showSuccessToast('Removed')
    } catch (e) {
      console.error('delete context file failed', e)
      showErrorToast('Failed to remove file')
    } finally {
      setBusyIds((s) => {
        const next = new Set(s)
        next.delete(id)
        return next
      })
    }
  }

  const onToggleRetrieval = async () => {
    const next = !retrievalOnly
    setRetrievalOnly(next) // optimistic
    setRetrievalSaving(true)
    try {
      await setRetrievalMode(sessionId, next)
    } catch (e) {
      // Rollback on failure so the UI reflects what the server believes.
      setRetrievalOnly(!next)
      showErrorToast(`Failed to update: ${errMsg(e)}`)
    } finally {
      setRetrievalSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Session settings</DialogTitle>
          <DialogDescription>
            Configure context and tools for this session. Changes apply
            to every subsequent agent turn.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-6 mt-2">
          <section className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-[var(--text-primary)] font-medium">
                <FileText size={16} className="text-[var(--icon-secondary)]" />
                <span>Context files</span>
                {files.length > 0 && (
                  <span className="text-[12px] text-[var(--text-tertiary)] tabular-nums">
                    {files.length}
                  </span>
                )}
              </div>
              <button
                type="button"
                onClick={onPick}
                disabled={uploading}
                className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md text-sm font-medium border border-[var(--border-btn-main)] hover:bg-[var(--fill-tsp-white-light)] disabled:opacity-50"
              >
                {uploading ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Upload size={14} />
                )}
                Upload
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept={ACCEPT}
                multiple
                onChange={onFiles}
                className="hidden"
              />
            </div>
            <p className="text-sm text-[var(--text-tertiary)]">
              Markdown files attached here are kept in the agent's prompt
              for every reply — specs, design notes, API references.
              Limit 256 KB per file, 20 files, 2 MB total.
            </p>

            <div className="flex items-center gap-2">
              <Globe size={14} className="text-[var(--icon-secondary)] flex-shrink-0" />
              <input
                type="url"
                value={urlValue}
                onChange={(e) => setUrlValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !urlBusy) void onAddUrl()
                }}
                placeholder="Paste a URL (docs, README, spec page)"
                disabled={urlBusy}
                className="flex-1 h-8 px-2 rounded-md text-sm bg-[var(--fill-tsp-white-light)] border border-[var(--border-light)] focus:outline-none focus:ring-1 focus:ring-[var(--text-brand)] disabled:opacity-50"
              />
              <button
                type="button"
                onClick={onAddUrl}
                disabled={urlBusy || !urlValue.trim()}
                className="inline-flex items-center gap-1 h-8 px-3 rounded-md text-sm font-medium border border-[var(--border-btn-main)] hover:bg-[var(--fill-tsp-white-light)] disabled:opacity-50"
              >
                {urlBusy ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                Add
              </button>
            </div>

            {loading && files.length === 0 ? (
              <div className="flex items-center justify-center py-6 text-[var(--text-tertiary)]">
                <Loader2 size={16} className="animate-spin" />
              </div>
            ) : files.length === 0 ? (
              <div className="rounded-md border border-dashed border-[var(--border-light)] py-6 text-center text-sm text-[var(--text-tertiary)]">
                No context files yet
              </div>
            ) : (
              <ul className="flex flex-col rounded-md border border-[var(--border-light)] divide-y divide-[var(--border-light)]">
                {files.map((f) => (
                  <li
                    key={f.id}
                    className="flex items-center gap-3 px-3 py-2"
                  >
                    <FileText
                      size={14}
                      className="shrink-0 text-[var(--icon-secondary)]"
                    />
                    <span
                      className="flex-1 min-w-0 truncate text-sm text-[var(--text-primary)]"
                      title={f.filename}
                    >
                      {f.filename}
                    </span>
                    <span className="shrink-0 text-xs tabular-nums text-[var(--text-tertiary)]">
                      {fmtSize(f.size)}
                    </span>
                    <button
                      type="button"
                      onClick={() => onDelete(f.id)}
                      disabled={busyIds.has(f.id)}
                      className="shrink-0 p-1 rounded hover:bg-[var(--fill-tsp-white-light)] text-[var(--icon-secondary)] disabled:opacity-50"
                      title="Remove"
                    >
                      {busyIds.has(f.id) ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : (
                        <Trash2 size={14} />
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="flex flex-col gap-2">
            <div className="flex items-center gap-2 text-[var(--text-primary)] font-medium">
              <Wrench size={16} className="text-[var(--icon-secondary)]" />
              <span>Tools</span>
            </div>

            <button
              type="button"
              onClick={onToggleRetrieval}
              disabled={retrievalSaving}
              className={cn(
                'flex items-start justify-between gap-3 p-3 rounded-md border text-left transition-colors',
                retrievalOnly
                  ? 'border-[var(--text-brand)] bg-[var(--fill-tsp-white-light)]'
                  : 'border-[var(--border-light)] hover:bg-[var(--fill-tsp-white-light)]',
                retrievalSaving && 'opacity-60',
              )}
            >
              <div className="flex flex-col gap-1 min-w-0">
                <div className="text-sm font-medium text-[var(--text-primary)]">
                  Retrieval-only mode
                </div>
                <div className="text-xs text-[var(--text-tertiary)] leading-snug">
                  Don't dump context files into every prompt. The agent
                  reaches them only by calling{' '}
                  <code className="font-mono">retrieve(query)</code>.
                  Recommended once your corpus is &gt; ~50 KB.
                </div>
              </div>
              <Switch on={retrievalOnly} />
            </button>

            <p className="text-sm text-[var(--text-tertiary)] mt-1">
              More per-session tools (custom MCP servers, web search
              toggle) coming next.
            </p>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function Switch({ on }: { on: boolean }) {
  return (
    <span
      className={cn(
        'relative inline-flex h-5 w-9 flex-shrink-0 items-center rounded-full transition-colors',
        on ? 'bg-[var(--text-brand)]' : 'bg-[var(--fill-tsp-gray-main)]',
      )}
      aria-hidden
    >
      <span
        className={cn(
          'inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform',
          on ? 'translate-x-[18px]' : 'translate-x-[3px]',
        )}
      />
    </span>
  )
}
