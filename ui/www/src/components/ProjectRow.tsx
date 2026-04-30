import { useState, type MouseEvent } from 'react'
import { Ellipsis, Pencil, Sparkles, Trash } from 'lucide-react'
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
import {
  deleteProject,
  renameProject,
  updateProjectSystemPrompt,
} from '@/api/projects'
import { showErrorToast, showSuccessToast } from '@/utils/toast'
import { cn } from '@/lib/utils'

interface Props {
  project: ProjectItem
  onDeleted: (projectId: string) => void
  onRenamed: (projectId: string, name: string) => void
  onPromptChanged: (projectId: string, prompt: string | null) => void
}

/** A single sidebar row — one project = one chat. */
export default function ProjectRow({
  project,
  onDeleted,
  onRenamed,
  onPromptChanged,
}: Props) {
  const navigate = useNavigate()
  const params = useParams<{ sessionId?: string }>()
  const showContextMenu = useContextMenu((s) => s.show)
  const showConfirmDialog = useDialog((s) => s.showConfirmDialog)
  const [menuOpen, setMenuOpen] = useState(false)
  const [promptOpen, setPromptOpen] = useState(false)
  const [promptDraft, setPromptDraft] = useState('')

  const sessionId = project.session_id
  const isCurrent = !!sessionId && params.sessionId === sessionId

  const handleClick = () => {
    if (sessionId) navigate(`/chat/${sessionId}`)
  }

  const openPromptDialog = () => {
    setPromptDraft(project.system_prompt ?? '')
    setPromptOpen(true)
  }

  const savePrompt = async () => {
    const trimmed = promptDraft.trim()
    const next = trimmed === '' ? null : trimmed
    if (next === (project.system_prompt ?? null)) {
      setPromptOpen(false)
      return
    }
    try {
      await updateProjectSystemPrompt(project.project_id, next)
      onPromptChanged(project.project_id, next)
      setPromptOpen(false)
      showSuccessToast('Prompt updated')
    } catch {
      showErrorToast('Failed to update prompt')
    }
  }

  const handleRename = async () => {
    const next = window.prompt('Project name', project.name)
    if (!next || next === project.name) return
    try {
      await renameProject(project.project_id, next)
      onRenamed(project.project_id, next)
    } catch {
      showErrorToast('Failed to rename project')
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
        createMenuItem('prompt', 'Edit prompt', { icon: Sparkles }),
        createDangerMenuItem('delete', 'Delete', { icon: Trash }),
      ],
      (itemKey) => {
        if (itemKey === 'rename') void handleRename()
        else if (itemKey === 'prompt') openPromptDialog()
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
          'group flex items-center rounded-[10px] cursor-pointer transition-colors w-full gap-[12px] h-[36px] flex-shrink-0 ps-[9px] pe-[2px] active:bg-[var(--fill-tsp-white-dark)]',
          isCurrent
            ? 'bg-[var(--fill-tsp-white-main)]'
            : 'hover:bg-[var(--fill-tsp-white-light)]',
        )}
      >
        <div className="shrink-0 size-[18px] flex items-center justify-center relative">
          {isBusy ? (
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
            <div className="size-[18px] rounded-full bg-[var(--fill-tsp-white-dark)]" />
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

      <Dialog open={promptOpen} onOpenChange={setPromptOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Project prompt — {project.name}</DialogTitle>
          </DialogHeader>
          <div className="text-xs text-[var(--text-tertiary)] mb-2">
            Appended to the agent's built-in instructions for this project's
            chat. Existing chats keep the prompt that was active when they were
            created.
          </div>
          <textarea
            value={promptDraft}
            onChange={(e) => setPromptDraft(e.target.value)}
            placeholder="e.g. You are a helpful research assistant focused on internal docs."
            className="w-full min-h-[160px] rounded-md border border-[var(--border-main)] bg-transparent p-3 text-sm outline-none focus:ring-2 focus:ring-[var(--text-brand)] resize-y"
          />
          <DialogFooter className="gap-2">
            <button
              onClick={() => setPromptOpen(false)}
              className="px-3 h-9 rounded-md border border-[var(--border-btn-main)] text-sm hover:bg-[var(--fill-tsp-white-light)]"
            >
              Cancel
            </button>
            <button
              onClick={savePrompt}
              className="px-3 h-9 rounded-md text-sm bg-[var(--Button-primary-black)] text-[var(--text-onblack)] hover:opacity-90"
            >
              Save
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
