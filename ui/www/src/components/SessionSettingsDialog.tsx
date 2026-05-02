import { useCallback, useEffect, useRef, useState } from 'react'
import { FileText, Loader2, Trash2, Upload, Wrench } from 'lucide-react'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from './ui/Dialog'
import {
  deleteContextFile,
  listContextFiles,
  uploadContextFile,
  type ContextFileSummary,
} from '@/api/agent'
import { showErrorToast, showSuccessToast } from '@/utils/toast'

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

/**
 * Per-session config. Currently surfaces:
 *
 *   - Context files: Markdown attachments rendered into the agent's
 *     extra_system_prompt for every turn. Server enforces caps (256 KB
 *     per file, 20 files, 2 MB total) — UI shows the friendly message
 *     when validation rejects an upload.
 *   - Tools: scaffold for upcoming per-session toggles (retrieve,
 *     web search, MCP). Disabled until backed.
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
  const fileInputRef = useRef<HTMLInputElement>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const list = await listContextFiles(sessionId)
      setFiles(list)
    } catch (e) {
      console.error('list context files failed', e)
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
    e.target.value = '' // allow re-selecting the same file later
    if (picked.length === 0) return
    setUploading(true)
    try {
      // Sequential — keeps server-side count/total caps deterministic.
      // Parallel uploads could each pass the per-file check yet collectively
      // exceed the total cap, leaving partial state.
      for (const f of picked) {
        const text = await f.text()
        try {
          await uploadContextFile(sessionId, f.name, text)
        } catch (err) {
          const msg =
            (err as { message?: string; msg?: string })?.message ??
            (err as { msg?: string })?.msg ??
            'upload failed'
          showErrorToast(`${f.name}: ${msg}`)
        }
      }
      await refresh()
    } finally {
      setUploading(false)
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
            <p className="text-sm text-[var(--text-tertiary)]">
              Per-session tools the agent can call — retrieve over
              attached files, search, custom MCP servers.
            </p>
            <div className="rounded-md border border-dashed border-[var(--border-light)] py-6 text-center text-sm text-[var(--text-tertiary)]">
              No tools configured
            </div>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  )
}
