import { useEffect } from 'react'
import { Minimize2 } from 'lucide-react'

import { useFilePanel } from '@/hooks/useFilePanel'
import { eventBus } from '@/utils/eventBus'
import { EVENT_SHOW_TOOL_PANEL } from '@/constants/event'
import { getFileType } from '@/utils/fileType'

/** Right-side panel for previewing user/agent attachments. */
export default function FilePanel() {
  const isShow = useFilePanel((s) => s.isShow)
  const visible = useFilePanel((s) => s.visible)
  const fileInfo = useFilePanel((s) => s.fileInfo)
  const setVisible = useFilePanel((s) => s.setVisible)
  const hideFilePanel = useFilePanel((s) => s.hideFilePanel)

  useEffect(() => {
    const off = eventBus.on(EVENT_SHOW_TOOL_PANEL, () => setVisible(false))
    return () => off()
  }, [setVisible])

  if (!visible || !isShow || !fileInfo) return null

  const { Preview } = getFileType(fileInfo.filename)

  return (
    <div className="h-full sm:h-[100vh] sm:sticky sm:top-0 sm:right-0 z-40 flex w-[50%] sm:ml-3 sm:py-3 sm:mr-4">
      <div className="bg-[var(--background-menu-white)] rounded-[22px] flex flex-col w-full h-full shadow-[0px_0px_8px_0px_rgba(0,0,0,0.02)] border border-black/8 dark:border-[var(--border-light)] overflow-hidden">
        <div className="flex items-center gap-2 p-4 border-b border-[var(--border-light)]">
          <div className="text-[var(--text-primary)] text-base font-semibold flex-1 truncate">
            {fileInfo.filename}
          </div>
          <button
            onClick={hideFilePanel}
            className="w-7 h-7 rounded-md inline-flex items-center justify-center cursor-pointer hover:bg-[var(--fill-tsp-gray-main)]"
          >
            <Minimize2 className="w-5 h-5 text-[var(--icon-tertiary)]" />
          </button>
        </div>
        <div className="flex-1 min-h-0">
          <Preview file={fileInfo} />
        </div>
      </div>
    </div>
  )
}
