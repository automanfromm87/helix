import { useEffect, useState } from 'react'
import { Bot, Github, PanelLeft } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import ChatBox from '@/components/ChatBox'
import UserMenu from '@/components/UserMenu'
import { HelixLogoTextIcon } from '@/components/icons'
import { SimpleBar } from '@/components/ui/SimpleBar'
import { createProject } from '@/api/projects'
import { useAuth } from '@/hooks/useAuth'
import { useClientConfig } from '@/hooks/useClientConfig'
import { useFilePanel } from '@/hooks/useFilePanel'
import { useLeftPanel } from '@/hooks/useLeftPanel'
import { usePendingMessage } from '@/hooks/usePendingMessage'
import { showErrorToast } from '@/utils/toast'
import type { FileInfo } from '@/api/file'

export default function HomePage() {
  const navigate = useNavigate()
  const { currentUser } = useAuth()
  const isLeftPanelShow = useLeftPanel((s) => s.isLeftPanelShow)
  const toggleLeftPanel = useLeftPanel((s) => s.toggleLeftPanel)
  const hideFilePanel = useFilePanel((s) => s.hideFilePanel)
  const [message, setMessage] = useState('')
  const [attachments, setAttachments] = useState<FileInfo[]>([])
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [showUserMenu, setShowUserMenu] = useState(false)
  const [userMenuTimeout, setUserMenuTimeout] = useState<number | null>(null)
  const { config } = useClientConfig()
  const showGithubButton = config?.show_github_button ?? false
  const githubRepositoryUrl =
    config?.github_repository_url ?? 'https://github.com/simpleyyt/ai-helix'

  useEffect(() => {
    hideFilePanel()
  }, [hideFilePanel])

  const avatarLetter = currentUser?.fullname?.charAt(0)?.toUpperCase() || 'M'

  const handleUserMenuEnter = () => {
    if (userMenuTimeout) {
      window.clearTimeout(userMenuTimeout)
      setUserMenuTimeout(null)
    }
    setShowUserMenu(true)
  }

  const handleUserMenuLeave = () => {
    const id = window.setTimeout(() => setShowUserMenu(false), 200)
    setUserMenuTimeout(id)
  }

  const handleSubmit = async () => {
    if (!message.trim() || isSubmitting) return
    setIsSubmitting(true)
    try {
      // 1:1 model: each new chat is a fresh project that ships with its own
      // session. The first user message becomes the project's first turn.
      const project = await createProject()
      const files = attachments.map((file) => ({
        file_id: file.file_id,
        filename: file.filename,
        content_type: file.content_type,
        size: file.size,
        upload_date: file.upload_date,
      }))
      // Stage the first message in module memory and navigate. ChatPage
      // takes() it once on the matching sessionId, sidestepping the
      // location.state double-consumption problem.
      usePendingMessage.getState().set({
        sessionId: project.session_id,
        message,
        files,
      })
      navigate(`/chat/${project.session_id}`)
    } catch (e) {
      console.error('Failed to create project:', e)
      showErrorToast('Failed to create project, please try again later')
      setIsSubmitting(false)
    }
  }

  return (
    <SimpleBar>
      <div className="flex flex-col h-full flex-1 min-w-0 mx-auto w-full sm:min-w-[390px] px-5 justify-center items-start gap-2 relative max-w-full sm:max-w-full">
        <div className="w-full pt-4 pb-4 px-5 bg-[var(--background-gray-main)] sticky top-0 z-10 mx-[-1.25]">
          <div className="flex justify-between items-center w-full absolute left-0 right-0">
            <div className="h-8 relative z-20 overflow-hidden flex gap-2 items-center flex-shrink-0">
              <div className="relative flex items-center">
                {!isLeftPanelShow && (
                  <div
                    onClick={toggleLeftPanel}
                    className="flex h-7 w-7 items-center justify-center cursor-pointer rounded-md hover:bg-[var(--fill-tsp-gray-main)]"
                  >
                    <PanelLeft className="size-5 text-[var(--icon-secondary)]" />
                  </div>
                )}
              </div>
              <div className="flex">
                <Bot size={30} />
                <HelixLogoTextIcon />
              </div>
            </div>
            <div className="flex items-center gap-2">
              {showGithubButton && (
                <a
                  href={githubRepositoryUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="items-center justify-center whitespace-nowrap font-medium transition-colors hover:opacity-90 px-[12px] gap-[6px] text-sm min-w-16 outline outline-1 -outline-offset-1 hover:bg-[var(--fill-tsp-white-light)] text-[var(--text-primary)] outline-[var(--border-btn-main)] bg-transparent hidden sm:flex rounded-[100px] relative h-[32px]"
                >
                  <Github className="size-[18px]" />
                  GitHub
                </a>
              )}
              <div
                className="relative flex items-center"
                onMouseEnter={handleUserMenuEnter}
                onMouseLeave={handleUserMenuLeave}
              >
                <div className="relative flex items-center justify-center font-bold cursor-pointer flex-shrink-0">
                  <div
                    className="relative flex items-center justify-center font-bold flex-shrink-0 rounded-full overflow-hidden"
                    style={{
                      width: 32,
                      height: 32,
                      fontSize: 16,
                      color: 'rgba(255, 255, 255, 0.9)',
                      backgroundColor: 'rgb(59, 130, 246)',
                    }}
                  >
                    {avatarLetter}
                  </div>
                </div>
                {showUserMenu && (
                  <div
                    onMouseEnter={handleUserMenuEnter}
                    onMouseLeave={handleUserMenuLeave}
                    className="absolute top-full right-0 mt-1 mr-[-15px] z-50"
                  >
                    <UserMenu />
                  </div>
                )}
              </div>
            </div>
          </div>
          <div className="h-8" />
        </div>
        <div className="w-full max-w-full sm:max-w-[768px] sm:min-w-[390px] mx-auto mt-[180px] mb-auto">
          <div className="w-full flex pl-4 items-center justify-start pb-4">
            <span
              className="text-[var(--text-primary)] text-start font-serif text-[32px] leading-[40px]"
              style={{ fontFamily: 'ui-serif, Georgia, Cambria, "Times New Roman", Times, serif' }}
            >
              Hello, {currentUser?.fullname}
              <br />
              <span className="text-[var(--text-tertiary)]">What can I do for you?</span>
            </span>
          </div>
          <div className="flex flex-col gap-1 w-full">
            <div className="flex flex-col bg-[var(--background-gray-main)] w-full">
              <div className="bg-[var(--background-gray-main)] rounded-[22px_22px_0px_0px]" />
              <ChatBox
                rows={2}
                value={message}
                onChange={setMessage}
                isRunning={false}
                attachments={attachments}
                onAttachmentsChange={setAttachments}
                onSubmit={handleSubmit}
              />
            </div>
          </div>
        </div>
      </div>
    </SimpleBar>
  )
}
