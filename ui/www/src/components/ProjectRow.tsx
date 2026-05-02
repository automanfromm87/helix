import { useEffect, useRef, useState, type KeyboardEvent, type MouseEvent } from 'react'
import { Check, Ellipsis, Pencil, Trash } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'

import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from './ui/Dialog'
import type { ProjectItem } from '@/types/response'
import { SessionStatus } from '@/types/response'
import {
  createDangerMenuItem,
  createMenuItem,
  useContextMenu,
} from '@/hooks/useContextMenu'
import { useDialog } from '@/hooks/useDialog'
import { deleteProject, renameProject } from '@/api/projects'
import { showErrorToast, showSuccessToast } from '@/utils/toast'
import { cn } from '@/lib/utils'

interface Props {
  project: ProjectItem
  onDeleted: (projectId: string) => void
  onRenamed: (projectId: string, name: string) => void
  /** When true, clicking the row toggles selection instead of navigating. */
  mergeMode?: boolean
  isSelected?: boolean
  onToggleSelected?: (sessionId: string) => void
}

/** A single sidebar row — one project = one chat. */
export default function ProjectRow({
  project,
  onDeleted,
  onRenamed,
  mergeMode = false,
  isSelected = false,
  onToggleSelected,
}: Props) {
  const navigate = useNavigate()
  const params = useParams<{ sessionId?: string }>()
  const showContextMenu = useContextMenu((s) => s.show)
  const showConfirmDialog = useDialog((s) => s.showConfirmDialog)
  const [menuOpen, setMenuOpen] = useState(false)
  const [renameOpen, setRenameOpen] = useState(false)
  const [renameDraft, setRenameDraft] = useState('')
  const [renaming, setRenaming] = useState(false)
  const renameInputRef = useRef<HTMLInputElement>(null)

  const sessionId = project.session_id
  const isCurrent = !!sessionId && params.sessionId === sessionId

  const handleClick = () => {
    if (mergeMode) {
      if (sessionId) onToggleSelected?.(sessionId)
      return
    }
    if (sessionId) navigate(`/chat/${sessionId}`)
  }

  const openRenameDialog = () => {
    setRenameDraft(project.name)
    setRenameOpen(true)
  }

  // Auto-focus + select-all on open so the user can just type the new name.
  useEffect(() => {
    if (renameOpen) {
      // setTimeout because the dialog mount + focus race otherwise misses.
      const t = window.setTimeout(() => {
        renameInputRef.current?.focus()
        renameInputRef.current?.select()
      }, 0)
      return () => window.clearTimeout(t)
    }
  }, [renameOpen])

  const submitRename = async () => {
    const next = renameDraft.trim()
    if (!next || next === project.name) {
      setRenameOpen(false)
      return
    }
    setRenaming(true)
    try {
      await renameProject(project.project_id, next)
      onRenamed(project.project_id, next)
      setRenameOpen(false)
      showSuccessToast('Renamed')
    } catch {
      showErrorToast('Failed to rename project')
    } finally {
      setRenaming(false)
    }
  }

  const onRenameKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      void submitRename()
    } else if (e.key === 'Escape') {
      setRenameOpen(false)
    }
  }

  const handleDelete = () => {
    showConfirmDialog({
      title: `Delete "${project.name}"?`,
      content: 'This will delete the project and its chat history.',
      confirmText: 'Delete',
      cancelText: 'Cancel',
      confirmType: 'danger',
      onConfirm: async () => {
        try {
          await deleteProject(project.project_id)
          onDeleted(project.project_id)
          if (isCurrent) navigate('/')
          showSuccessToast('Project deleted')
        } catch {
          showErrorToast('Failed to delete project')
        }
      },
    })
  }

  const handleEllipsisClick = (event: MouseEvent<HTMLDivElement>) => {
    event.stopPropagation()
    const target = event.currentTarget as HTMLElement
    setMenuOpen(true)
    showContextMenu(
      project.project_id,
      target,
      [
        createMenuItem('rename', 'Rename', { icon: Pencil }),
        createDangerMenuItem('delete', 'Delete', { icon: Trash }),
      ],
      (itemKey) => {
        if (itemKey === 'rename') openRenameDialog()
        else if (itemKey === 'delete') handleDelete()
      },
      () => setMenuOpen(false),
    )
  }

  const displayTitle = project.title || project.name
  const isBusy =
    project.status === SessionStatus.RUNNING ||
    project.status === SessionStatus.PENDING
  const isWaiting = project.status === SessionStatus.WAITING

  return (
    <>
      <div
        onClick={handleClick}
        className={cn(
          'group relative flex items-center rounded-[10px] cursor-pointer transition-colors w-full gap-[12px] h-[36px] flex-shrink-0 ps-[9px] pe-[2px] active:bg-[var(--fill-tsp-white-dark)]',
          isCurrent
            ? 'bg-[var(--fill-tsp-white-main)]'
            : 'hover:bg-[var(--fill-tsp-white-light)]',
        )}
      >
        <span
          className={cn(
            'absolute left-0 top-1/2 -translate-y-1/2 h-5 w-[3px] rounded-r-full bg-[var(--text-brand)] transition-opacity',
            isCurrent ? 'opacity-100' : 'opacity-0',
          )}
          aria-hidden
        />
        <div className="shrink-0 size-[18px] flex items-center justify-center relative">
          {mergeMode ? (
            <div
              className={cn(
                'size-[16px] rounded-[4px] border inline-flex items-center justify-center transition-colors',
                isSelected
                  ? 'bg-[var(--text-brand)] border-[var(--text-brand)] text-white'
                  : 'border-[var(--border-main)] bg-transparent',
              )}
            >
              {isSelected && <Check size={11} strokeWidth={3} />}
            </div>
          ) : isBusy ? (
            <div
              className="border rounded-full animate-spin"
              style={{
                width: 18,
                height: 18,
                borderWidth: 2,
                borderColor: 'var(--fill-blue)',
                borderTopColor: 'var(--icon-brand)',
              }}
            />
          ) : isWaiting ? (
            <svg height="18" width="18" fill="none" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">
              <circle cx="8" cy="8" r="6.5" stroke="var(--function-warning)" strokeDasharray="2.44 1.62" strokeWidth="1.5" />
            </svg>
          ) : (
            <div className="size-[6px] rounded-full bg-[var(--icon-tertiary)] opacity-60" />
          )}
        </div>
        <div className="flex-1 min-w-0 flex gap-[4px] items-center text-[14px] text-[var(--text-primary)]">
          <span className="truncate" title={displayTitle}>
            {displayTitle}
          </span>
        </div>
        <div className="shrink-0 flex items-center gap-1">
          <div
            onClick={handleEllipsisClick}
            className={cn(
              'group-hover:flex hidden size-8 rounded-[8px] cursor-pointer items-center justify-center hover:bg-[var(--fill-tsp-white-light)]',
              menuOpen && '!flex bg-[var(--fill-tsp-white-light)]',
            )}
          >
            <Ellipsis size={18} className="text-[var(--icon-tertiary)]" />
          </div>
        </div>
      </div>

      <Dialog open={renameOpen} onOpenChange={setRenameOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Rename project</DialogTitle>
          </DialogHeader>
          <input
            ref={renameInputRef}
            type="text"
            value={renameDraft}
            onChange={(e) => setRenameDraft(e.target.value)}
            onKeyDown={onRenameKey}
            placeholder="Project name"
            className="w-full h-10 rounded-md border border-[var(--border-main)] bg-transparent px-3 text-sm outline-none focus:ring-2 focus:ring-[var(--text-brand)]"
          />
          <DialogFooter className="gap-2">
            <button
              type="button"
              onClick={() => setRenameOpen(false)}
              disabled={renaming}
              className="px-3 h-9 rounded-md border border-[var(--border-btn-main)] text-sm hover:bg-[var(--fill-tsp-white-light)] disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={submitRename}
              disabled={
                renaming ||
                !renameDraft.trim() ||
                renameDraft.trim() === project.name
              }
              className="px-3 h-9 rounded-md text-sm bg-[var(--Button-primary-black)] text-[var(--text-onblack)] hover:opacity-90 disabled:opacity-50"
            >
              {renaming ? 'Saving…' : 'Save'}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
