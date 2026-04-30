import { Eye, FileSearch } from 'lucide-react'

import type { AttachmentsContent } from '@/types/message'
import type { FileInfo } from '@/api/file'
import { useFilePanel } from '@/hooks/useFilePanel'
import { useSessionFileList } from '@/hooks/useSessionFileList'
import { formatFileSize, getFileType, getFileTypeText } from '@/utils/fileType'

interface Props {
  content: AttachmentsContent
  hideAllFilesButton?: boolean
}

function AttachmentTile({ attachment, onClick }: { attachment: FileInfo; onClick: () => void }) {
  const { Icon } = getFileType(attachment.filename)
  return (
    <div
      onClick={onClick}
      className="flex items-center gap-1.5 p-2 pr-2.5 w-[280px] group/attach relative overflow-hidden cursor-pointer rounded-[12px] border-[0.5px] border-[var(--border-dark)] bg-[var(--background-menu-white)] hover:bg-[var(--background-tsp-menu-white)]"
    >
      <div className="flex items-center justify-center w-8 h-8 rounded-md">
        <Icon size={20} />
      </div>
      <div className="flex flex-col gap-0.5 flex-1 min-w-0">
        <div className="flex-1 min-w-0 flex items-center">
          <div className="text-sm text-[var(--text-primary)] text-ellipsis overflow-hidden whitespace-nowrap flex-1 min-w-0">
            {attachment.filename}
          </div>
        </div>
        <div className="text-xs text-[var(--text-tertiary)]">
          {getFileTypeText(attachment.filename)} · {formatFileSize(attachment.size)}
        </div>
      </div>
      <div className="items-center justify-center cursor-pointer rounded-md w-6 h-6 border border-[var(--border-main)] flex opacity-0 group-hover/attach:opacity-100">
        <Eye size={16} className="text-[var(--icon-secondary)]" />
      </div>
    </div>
  )
}

export default function AttachmentsMessage({ content, hideAllFilesButton }: Props) {
  const showFilePanel = useFilePanel((s) => s.showFilePanel)
  const showSessionFileList = useSessionFileList((s) => s.showSessionFileList)

  if (content.role === 'user') {
    return (
      <div className="flex flex-col flex-wrap gap-2 items-end justify-end">
        <div className="flex gap-2 flex-wrap max-w-[568px] justify-end">
          {content.attachments.map((a) => (
            <AttachmentTile key={a.file_id} attachment={a} onClick={() => showFilePanel(a)} />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col flex-wrap gap-2 justify-start">
      <div className="flex gap-2 flex-wrap max-w-[568px]">
        {content.attachments.map((a) => (
          <AttachmentTile key={a.file_id} attachment={a} onClick={() => showFilePanel(a)} />
        ))}
        {!hideAllFilesButton && (
          <button
            onClick={() => showSessionFileList()}
            className="h-[54px] pl-4 pr-1.5 flex items-center justify-center gap-1.5 w-[280px] rounded-[12px] border-[0.5px] border-[var(--border-dark)] bg-[var(--background-menu-white)] hover:bg-[var(--background-tsp-menu-white)]"
          >
            <FileSearch size={16} />
            <span className="text-sm text-[var(--icon-secondary)]">View all files in this task</span>
          </button>
        )}
      </div>
    </div>
  )
}
