import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  useMemo,
} from 'react'
import { ChevronLeft, ChevronRight, Loader2, RefreshCcw, X } from 'lucide-react'

import { uploadFile as apiUploadFile, type FileInfo } from '@/api/file'
import { formatFileSize, getFileType, getFileTypeText } from '@/utils/fileType'
import { useFilePanel } from '@/hooks/useFilePanel'

export interface ChatBoxFilesHandle {
  uploadFile: () => void
  getFiles: () => ExtendedFileInfo[]
  isAllUploaded: () => boolean
}

interface ExtendedFileInfo extends FileInfo {
  status?: 'uploading' | 'success' | 'failed'
  file?: File | null
}

interface Props {
  attachments: FileInfo[]
  onChange?: (files: FileInfo[]) => void
}

const ChatBoxFiles = forwardRef<ChatBoxFilesHandle, Props>(({ attachments, onChange }, ref) => {
  const [files, setFiles] = useState<ExtendedFileInfo[]>(attachments)
  const fileInput = useRef<HTMLInputElement>(null)
  const scrollContainer = useRef<HTMLDivElement>(null)
  const [canScrollLeft, setCanScrollLeft] = useState(false)
  const [canScrollRight, setCanScrollRight] = useState(false)
  const showFilePanel = useFilePanel((s) => s.showFilePanel)

  useEffect(() => {
    setFiles(attachments)
  }, [attachments])

  // Notify parent when uploads complete (only success files are kept upstream).
  useEffect(() => {
    onChange?.(files.filter((f) => f.status !== 'failed' && f.status !== 'uploading'))
  }, [files, onChange])

  const updateScrollButtons = () => {
    const c = scrollContainer.current
    if (!c) return
    setCanScrollLeft(c.scrollLeft > 0)
    setCanScrollRight(c.scrollLeft < c.scrollWidth - c.clientWidth - 5)
  }

  useEffect(() => {
    updateScrollButtons()
  }, [files])

  const triggerFileSelect = () => fileInput.current?.click()

  const processUpload = async (file: File) => {
    const temp: ExtendedFileInfo = {
      file_id: `temp-${Date.now()}-${Math.random()}`,
      filename: file.name,
      content_type: file.type,
      size: file.size,
      upload_date: new Date().toISOString(),
      status: 'uploading',
      file,
    }
    setFiles((prev) => [...prev, temp])
    try {
      const uploaded = await apiUploadFile(file)
      setFiles((prev) =>
        prev.map((f) =>
          f.file_id === temp.file_id ? { ...uploaded, status: 'success', file: null } : f,
        ),
      )
    } catch (e) {
      console.error('Upload failed:', e)
      setFiles((prev) =>
        prev.map((f) => (f.file_id === temp.file_id ? { ...f, status: 'failed' } : f)),
      )
    }
  }

  const handleFileSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files
    if (!selected || selected.length === 0) return
    for (const f of Array.from(selected)) {
      await processUpload(f)
    }
    event.target.value = ''
  }

  const removeFile = (fileId: string) =>
    setFiles((prev) => prev.filter((f) => f.file_id !== fileId))

  const retryUpload = async (fileInfo: ExtendedFileInfo) => {
    if (!fileInfo.file) return
    setFiles((prev) =>
      prev.map((f) => (f.file_id === fileInfo.file_id ? { ...f, status: 'uploading' } : f)),
    )
    try {
      const uploaded = await apiUploadFile(fileInfo.file)
      setFiles((prev) =>
        prev.map((f) =>
          f.file_id === fileInfo.file_id ? { ...uploaded, status: 'success', file: null } : f,
        ),
      )
    } catch (e) {
      console.error('Retry upload failed:', e)
      setFiles((prev) =>
        prev.map((f) => (f.file_id === fileInfo.file_id ? { ...f, status: 'failed' } : f)),
      )
    }
  }

  const isAllUploaded = useMemo(
    () => files.every((f) => f.status === 'success' || f.status === undefined),
    [files],
  )

  useImperativeHandle(ref, () => ({
    uploadFile: triggerFileSelect,
    getFiles: () => files,
    isAllUploaded: () => isAllUploaded,
  }))

  const handleFileClick = (file: ExtendedFileInfo) => {
    if (file.status === 'success' || file.status === undefined) showFilePanel(file)
  }

  const scrollBy = (dx: number) =>
    scrollContainer.current?.scrollBy({ left: dx, behavior: 'smooth' })

  return (
    <>
      {files.length > 0 && (
        <div className="w-full relative rounded-md overflow-hidden flex-shrink-0 pb-3 -mb-3">
          {canScrollLeft && (
            <div className="absolute top-0 bottom-0 left-0 z-10 flex h-full items-center px-3">
              <button
                onClick={() => scrollBy(-280)}
                className="flex h-7 w-7 items-center justify-center rounded-full border border-[var(--border-white)] bg-[var(--background-menu-white)] hover:bg-[var(--fill-tsp-white-main)]"
              >
                <ChevronLeft size={14} />
              </button>
            </div>
          )}
          <div
            ref={scrollContainer}
            onScroll={updateScrollButtons}
            className="w-full overflow-x-auto overflow-y-hidden scrollbar-hide pb-[10px] -mb-[10px] pl-[10px] pr-2 flex"
          >
            <div className="flex gap-3">
              {files.map((file) => {
                const { Icon } = getFileType(file.filename)
                return (
                  <div
                    key={file.file_id}
                    onClick={() => handleFileClick(file)}
                    className="flex items-center gap-1.5 p-2 pr-2.5 w-[280px] rounded-[10px] bg-[var(--fill-tsp-white-main)] group/attach relative overflow-hidden cursor-pointer hover:bg-[var(--fill-tsp-white-dark)]"
                  >
                    <div className="flex items-center justify-center w-8 h-8 rounded-md">
                      {file.status === 'uploading' ? (
                        <Loader2 size={20} className="animate-spin" />
                      ) : (
                        <Icon size={20} />
                      )}
                    </div>
                    <div className="flex flex-col gap-0.5 flex-1 min-w-0">
                      <div className="flex-1 min-w-0 flex items-center">
                        <div className="text-sm text-[var(--text-primary)] text-ellipsis overflow-hidden whitespace-nowrap flex-1 min-w-0">
                          {file.filename}
                        </div>
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            removeFile(file.file_id)
                          }}
                          className="hidden group-hover/attach:flex rounded-full p-[2px] bg-[var(--icon-tertiary)]"
                        >
                          <X size={10} className="text-white" />
                        </button>
                      </div>
                      <div className="text-xs text-[var(--text-tertiary)]">
                        {file.status === 'failed' ? (
                          <span className="text-[var(--function-error)] flex items-center gap-1">
                            Upload failed
                            <RefreshCcw
                              size={14}
                              className="cursor-pointer hover:opacity-85"
                              onClick={(e) => {
                                e.stopPropagation()
                                retryUpload(file)
                              }}
                            />
                          </span>
                        ) : file.status === 'uploading' ? (
                          <span>Uploading...</span>
                        ) : (
                          <span>
                            {getFileTypeText(file.filename)} · {formatFileSize(file.size)}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
          {canScrollRight && (
            <div className="absolute top-0 bottom-0 right-0 z-10 flex h-full items-center px-3">
              <button
                onClick={() => scrollBy(280)}
                className="flex h-7 w-7 items-center justify-center rounded-full border border-[var(--border-white)] bg-[var(--background-menu-white)] hover:bg-[var(--fill-tsp-white-main)]"
              >
                <ChevronRight size={14} />
              </button>
            </div>
          )}
        </div>
      )}
      <input
        ref={fileInput}
        type="file"
        multiple
        className="hidden"
        onChange={handleFileSelect}
      />
    </>
  )
})

ChatBoxFiles.displayName = 'ChatBoxFiles'

export default ChatBoxFiles
