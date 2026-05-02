import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Folder, FolderPlus, GitMerge, Loader2, MessageSquareDashed, PanelLeft, X } from 'lucide-react'

import ProjectRow from './ProjectRow'
import SkillsSection from './SkillsSection'
import { useLeftPanel } from '@/hooks/useLeftPanel'
import { createProject, listProjects } from '@/api/projects'
import { mergeSessions } from '@/api/agent'
import type { ProjectItem } from '@/types/response'
import { showErrorToast, showSuccessToast } from '@/utils/toast'
import { cn } from '@/lib/utils'

export default function LeftPanel() {
  const navigate = useNavigate()
  const location = useLocation()
  const isLeftPanelShow = useLeftPanel((s) => s.isLeftPanelShow)
  const toggleLeftPanel = useLeftPanel((s) => s.toggleLeftPanel)
  const [projects, setProjects] = useState<ProjectItem[]>([])
  const [isListScrolled, setIsListScrolled] = useState(false)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  // Merge multi-select: when active, checkboxes appear on each row and
  // clicking toggles the session in/out of `selectedForMerge` instead of
  // navigating. Hitting Merge button calls the API; backend infers
  // direction from branch (fork/* = source).
  const [mergeMode, setMergeMode] = useState(false)
  const [selectedForMerge, setSelectedForMerge] = useState<Set<string>>(new Set())
  const [merging, setMerging] = useState(false)

  // Refresh project list on every route change so titles, statuses, and
  // newly-created sessions show up without a page reload.
  useEffect(() => {
    void listProjects()
      .then((res) => setProjects(res.projects))
      .catch((e) => console.error('Failed to fetch projects:', e))
  }, [location.pathname])

  // Cmd+K — quick "new chat" shortcut. 1:1 model: a new chat is a new project.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        void handleNewProject()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigate])

  const handleNewProject = async () => {
    try {
      const created = await createProject()
      // The freshly-created project ships with a session ID — jump straight
      // into the chat instead of leaving the user on a placeholder.
      setProjects((prev) => [
        ...prev,
        {
          project_id: created.project_id,
          name: created.name,
          system_prompt: created.system_prompt ?? null,
          session_id: created.session_id,
          title: null,
          latest_message: null,
          latest_message_at: null,
          status: null,
          unread_message_count: 0,
          is_shared: false,
        },
      ])
      navigate(`/chat/${created.session_id}`)
    } catch (e) {
      console.error('Failed to create project:', e)
      showErrorToast('Failed to create project')
    }
  }

  const handleProjectDeleted = (projectId: string) =>
    setProjects((prev) => prev.filter((p) => p.project_id !== projectId))

  const handleProjectRenamed = (projectId: string, name: string) =>
    setProjects((prev) =>
      // Mirror the backend: update both `name` and `title`. The sidebar
      // label is `title || name`, so leaving an old auto-derived title
      // in place would mask the user's rename until the next reload.
      prev.map((p) =>
        p.project_id === projectId ? { ...p, name, title: name } : p,
      ),
    )

  const handleListScroll = () => {
    if (scrollContainerRef.current) {
      setIsListScrolled(scrollContainerRef.current.scrollTop > 0)
    }
  }

  const toggleMergeMode = () => {
    setMergeMode((prev) => {
      if (prev) setSelectedForMerge(new Set())
      return !prev
    })
  }

  const toggleSessionSelected = (sessionId: string) => {
    setSelectedForMerge((prev) => {
      const next = new Set(prev)
      if (next.has(sessionId)) next.delete(sessionId)
      else if (next.size < 2) next.add(sessionId)
      return next
    })
  }

  const handleMerge = async () => {
    if (selectedForMerge.size !== 2) return
    const [a, b] = Array.from(selectedForMerge)
    setMerging(true)
    try {
      const result = await mergeSessions(a, b)
      if (result.status === 'merged' || result.status === 'resolved') {
        const resolvedNote =
          result.resolved_files && result.resolved_files.length > 0
            ? ` · AI resolved ${result.resolved_files.length} conflict${result.resolved_files.length === 1 ? '' : 's'}`
            : ''
        showSuccessToast(`Merged · fork removed${resolvedNote}`)
        setMergeMode(false)
        setSelectedForMerge(new Set())
        navigate(`/chat/${result.target_session_id}`)
      } else if (result.status === 'noop') {
        showSuccessToast('Already up to date — nothing to merge')
        setMergeMode(false)
        setSelectedForMerge(new Set())
      } else {
        // conflict (LLM couldn't resolve some) or failed
        const unresolved = result.unresolved_files?.length ?? 0
        showErrorToast(
          unresolved > 0
            ? `Merge needs manual fix on ${unresolved} file(s); open the target session and let the agent finish.`
            : (result.error || 'Merge failed'),
        )
      }
    } catch (e: any) {
      console.error('merge failed', e)
      showErrorToast(e?.response?.data?.message || 'Merge failed')
    } finally {
      setMerging(false)
    }
  }

  return (
    <div
      className={
        isLeftPanelShow
          ? 'h-full flex flex-col'
          : 'h-full flex flex-col fixed top-0 start-0 bottom-0 z-[1]'
      }
      style={{
        width: isLeftPanelShow ? 300 : 24,
        transition: isLeftPanelShow
          ? 'width 0.28s cubic-bezier(0.4, 0, 0.2, 1)'
          : 'width 0.36s cubic-bezier(0.4, 0, 0.2, 1)',
      }}
    >
      <div
        className={cn(
          isLeftPanelShow
            ? 'flex flex-col overflow-hidden bg-[var(--background-nav)] h-full opacity-100 translate-x-0'
            : 'flex flex-col overflow-hidden bg-[var(--background-nav)] fixed top-1 start-1 bottom-1 z-[1] dark:border-[1px] border border-[var(--border-main)] dark:border-[var(--border-light)] rounded-xl shadow-[0px_8px_32px_0px_rgba(0,0,0,0.16),0px_0px_0px_1px_rgba(0,0,0,0.06)] opacity-0 pointer-events-none -translate-x-10',
        )}
        style={{
          width: isLeftPanelShow ? 300 : 0,
          transition: 'opacity 0.2s, transform 0.2s, width 0.2s',
        }}
      >
        <div className="flex items-center px-3 h-[52px] flex-shrink-0">
          <div className="flex justify-between w-full px-1 pt-2">
            <div className="relative flex">
              <div
                onClick={toggleLeftPanel}
                className="flex h-7 w-7 items-center justify-center cursor-pointer hover:bg-[var(--fill-tsp-gray-main)] rounded-md"
              >
                <PanelLeft className="h-5 w-5 text-[var(--icon-secondary)]" />
              </div>
            </div>
            <button
              type="button"
              onClick={toggleMergeMode}
              title={mergeMode ? 'Exit merge mode' : 'Select two sessions to merge'}
              className={cn(
                'flex h-7 w-7 items-center justify-center rounded-md',
                mergeMode
                  ? 'bg-[var(--text-brand)] text-white'
                  : 'cursor-pointer hover:bg-[var(--fill-tsp-gray-main)] text-[var(--icon-secondary)]',
              )}
            >
              {mergeMode ? <X size={16} /> : <GitMerge size={16} />}
            </button>
          </div>
        </div>

        <div className="flex flex-col flex-1 min-h-0 px-[8px] pb-0 gap-px">
          <div
            onClick={handleNewProject}
            className="flex items-center rounded-[10px] cursor-pointer transition-colors w-full gap-[12px] h-[36px] ps-[9px] pe-[2px] hover:bg-[var(--fill-tsp-white-light)]"
          >
            <div className="shrink-0 size-[18px] flex items-center justify-center">
              <FolderPlus size={18} className="text-[var(--text-primary)]" />
            </div>
            <div className="flex-1 min-w-0 flex gap-[4px] items-center text-[14px] text-[var(--text-primary)]">
              <span className="truncate">New Project</span>
            </div>
          </div>

          <SkillsSection />

          <div className="-mx-[8px] mt-[8px] mb-[4px] border-t border-[var(--border-main)]" />

          <div className="flex items-center gap-[12px] h-[36px] ps-[9px] pe-[6px] mt-[4px]">
            <div className="shrink-0 size-[18px] flex items-center justify-center">
              <Folder size={18} className="text-[var(--text-primary)]" />
            </div>
            <span className="flex-1 min-w-0 text-[14px] text-[var(--text-primary)]">
              Projects
            </span>
            {projects.length > 0 && (
              <span className="text-[12px] text-[var(--text-tertiary)] tabular-nums pe-[14px]">
                {projects.length}
              </span>
            )}
          </div>

          <div className="flex flex-col flex-1 min-h-0 -mx-[8px] overflow-hidden">
            <div
              className={cn(
                'w-full border-t border-[var(--border-main)] transition-opacity duration-200',
                isListScrolled ? 'opacity-100' : 'opacity-0',
              )}
            />
            <div
              ref={scrollContainerRef}
              onScroll={handleListScroll}
              className="flex flex-col flex-1 min-h-0 overflow-y-auto overflow-x-hidden pb-5 px-[8px] gap-px"
            >
              {projects.length === 0 ? (
                <div className="flex flex-col items-center justify-center gap-4 py-8">
                  <div className="flex flex-col items-center gap-2 text-[var(--text-tertiary)]">
                    <MessageSquareDashed size={38} />
                    <span className="text-sm font-medium">Create a project to get started</span>
                  </div>
                </div>
              ) : (
                projects.map((project) => (
                  <ProjectRow
                    key={project.project_id}
                    project={project}
                    onDeleted={handleProjectDeleted}
                    onRenamed={handleProjectRenamed}
                    mergeMode={mergeMode}
                    isSelected={
                      project.session_id
                        ? selectedForMerge.has(project.session_id)
                        : false
                    }
                    onToggleSelected={(sessionId) => toggleSessionSelected(sessionId)}
                  />
                ))
              )}
            </div>
          </div>
        </div>
        {mergeMode && (
          <div className="flex flex-col gap-1 px-3 py-2 border-t border-[var(--border-light)] bg-[var(--background-nav)] flex-shrink-0">
            <div className="text-[11px] text-[var(--text-tertiary)] tabular-nums">
              {selectedForMerge.size} / 2 selected
            </div>
            <button
              type="button"
              onClick={handleMerge}
              disabled={selectedForMerge.size !== 2 || merging}
              className={cn(
                'h-9 rounded-md inline-flex items-center justify-center gap-1.5 text-[13px] font-medium transition-colors',
                selectedForMerge.size === 2 && !merging
                  ? 'bg-[var(--Button-primary-black)] text-[var(--text-onblack)] cursor-pointer hover:opacity-90'
                  : 'bg-[var(--fill-tsp-white-dark)] text-[var(--text-tertiary)] cursor-not-allowed',
              )}
            >
              {merging ? (
                <>
                  <Loader2 size={14} className="animate-spin" />
                  Merging…
                </>
              ) : (
                <>
                  <GitMerge size={14} />
                  Merge selected
                </>
              )}
            </button>
            <div className="text-[10.5px] text-[var(--text-tertiary)] leading-snug">
              Direction is inferred from branches: the fork session merges
              into the parent. Conflicts get auto-resolved by Claude.
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
