import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { FolderPlus, MessageSquareDashed, PanelLeft } from 'lucide-react'

import ProjectRow from './ProjectRow'
import SkillsSection from './SkillsSection'
import { useLeftPanel } from '@/hooks/useLeftPanel'
import { createProject, listProjects } from '@/api/projects'
import type { ProjectItem } from '@/types/response'
import { showErrorToast } from '@/utils/toast'
import { cn } from '@/lib/utils'

export default function LeftPanel() {
  const navigate = useNavigate()
  const location = useLocation()
  const isLeftPanelShow = useLeftPanel((s) => s.isLeftPanelShow)
  const toggleLeftPanel = useLeftPanel((s) => s.toggleLeftPanel)
  const [projects, setProjects] = useState<ProjectItem[]>([])
  const [isListScrolled, setIsListScrolled] = useState(false)
  const scrollContainerRef = useRef<HTMLDivElement>(null)

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
      prev.map((p) => (p.project_id === projectId ? { ...p, name } : p)),
    )

  const handleProjectPromptChanged = (
    projectId: string,
    prompt: string | null,
  ) =>
    setProjects((prev) =>
      prev.map((p) =>
        p.project_id === projectId ? { ...p, system_prompt: prompt } : p,
      ),
    )

  const handleListScroll = () => {
    if (scrollContainerRef.current) {
      setIsListScrolled(scrollContainerRef.current.scrollTop > 0)
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

          <div className="flex flex-col flex-1 min-h-0 -mx-[8px] mt-[4px] overflow-hidden">
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
                    onPromptChanged={handleProjectPromptChanged}
                  />
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
