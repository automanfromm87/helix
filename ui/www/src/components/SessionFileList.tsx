import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { X } from 'lucide-react'

import { Dialog, DialogContent, DialogHeader, DialogTitle } from './ui/Dialog'
import { useSessionFileList } from '@/hooks/useSessionFileList'
import { useFilePanel } from '@/hooks/useFilePanel'
import { getSessionFiles, getSharedSessionFiles } from '@/api/agent'
import type { FileInfo } from '@/api/file'
import { formatFileSize, getFileType, getFileTypeText } from '@/utils/fileType'

export default function SessionFileList() {
  const { sessionId } = useParams<{ sessionId?: string }>()
  const visible = useSessionFileList((s) => s.visible)
  const shared = useSessionFileList((s) => s.shared)
  const hide = useSessionFileList((s) => s.hideSessionFileList)
  const showFilePanel = useFilePanel((s) => s.showFilePanel)
  const [files, setFiles] = useState<FileInfo[]>([])

  useEffect(() => {
    if (!visible || !sessionId) return
    const loader = shared ? getSharedSessionFiles : getSessionFiles
    void loader(sessionId).then(setFiles).catch(console.error)
  }, [visible, sessionId, shared])

  return (
    <Dialog open={visible} onOpenChange={(open) => (open ? null : hide())}>
      <DialogContent showCloseButton={false} className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center justify-between">
            <span>All Files in This Task</span>
            <button onClick={hide} className="rounded-md p-1 hover:bg-[var(--fill-tsp-white-main)]">
              <X size={18} />
            </button>
          </DialogTitle>
        </DialogHeader>
        <div className="max-h-[60vh] overflow-y-auto">
          {files.length === 0 ? (
            <div className="text-center text-[var(--text-tertiary)] text-sm py-8">No Content</div>
          ) : (
            <div className="grid grid-cols-1 gap-2">
              {files.map((f) => {
                const { Icon } = getFileType(f.filename)
                return (
                  <button
                    key={f.file_id}
                    onClick={() => {
                      showFilePanel(f)
                      hide()
                    }}
                    className="flex items-center gap-2 px-3 py-2 rounded-md hover:bg-[var(--fill-tsp-white-main)] text-left"
                  >
                    <Icon size={20} />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-[var(--text-primary)] truncate">{f.filename}</div>
                      <div className="text-xs text-[var(--text-tertiary)]">
                        {getFileTypeText(f.filename)} · {formatFileSize(f.size)}
                      </div>
                    </div>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
