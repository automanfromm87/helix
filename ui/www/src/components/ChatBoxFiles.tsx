import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  useMemo,
} from 'react'
import { ChevronLeft, ChevronRight, Loader2, RefreshCcw, X } from 'lucide-react'

import { uploadFile as apiUploadFile, getFileDownloadUrl, type FileInfo } from '@/api/file'
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

  // Track the IDs we last notified the parent about. Without this, the
  // pair of effects below — `attachments` → `files`, and `files` →
  // `onChange(...)` — forms a feedback loop: onChange calls
  // `setAttachments` upstream with a fresh array reference (parent doesn't
  // memoize), parent re-renders, the new `attachments` ref triggers
  // `setFiles(attachments)`, which triggers the upward effect again. The
  // payload values are identical each cycle but the references aren't, so
  // React never bails out and we trip "Maximum update depth exceeded".
  const lastNotifiedIds = useRef<string>('')

  useEffect(() => {
    setFiles((prev) => {
      // Bail when content is structurally the same — keeps `prev` reference
      // stable so the downstream `onChange` effect doesn't fire spuriously.
      if (
        prev.length === attachments.length &&
        prev.every((p, i) => p.file_id === attachments[i]?.file_id)
      ) {
        return prev
      }
      return attachments
    })
  }, [attachments])

  // Notify parent when uploads complete (only success files are kept upstream).
  useEffect(() => {
    const ready = files.filter((f) => f.status !== 'failed' && f.status !== 'uploading')
    const ids = ready.map((f) => f.file_id).join('|')
    if (ids === lastNotifiedIds.current) return
    lastNotifiedIds.current = ids
    onChange?.(ready)
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
                const isImg =
                  file.content_type?.startsWith('image/') ||
                  /\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(file.filename ?? '')
                if (isImg) {
                  return (
                    <ImageStagingTile
                      key={file.file_id}
                      file={file}
                      onClick={() => handleFileClick(file)}
                      onRemove={() => removeFile(file.file_id)}
                      onRetry={() => retryUpload(file)}
                    />
                  )
                }
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


/**
 * Compact thumbnail tile shown in the ChatBox composer for image files
 * staged for upload. Uses an object URL while still uploading (so the
 * preview is instant and works without a backend round-trip), then swaps
 * to the signed-download URL once the upload succeeds.
 */
function ImageStagingTile({
  file,
  onClick,
  onRemove,
  onRetry,
}: {
  file: ExtendedFileInfo
  onClick: () => void
  onRemove: () => void
  onRetry: () => void
}) {
  const [previewUrl, setPreviewUrl] = useState<string>('')

  useEffect(() => {
    let cancelled = false
    let revokeMe: string | null = null
    if (file.file) {
      const url = URL.createObjectURL(file.file)
      revokeMe = url
      setPreviewUrl(url)
    } else if (file.status !== 'uploading' && file.file_id && !file.file_id.startsWith('temp-')) {
      void getFileDownloadUrl(file)
        .then((u) => {
          if (!cancelled) setPreviewUrl(u)
        })
        .catch(() => {})
    }
    return () => {
      cancelled = true
      if (revokeMe) URL.revokeObjectURL(revokeMe)
    }
  }, [file])

  const failed = file.status === 'failed'
  const uploading = file.status === 'uploading'

  return (
    <div
      onClick={onClick}
      className="relative w-[88px] h-[88px] rounded-[10px] overflow-hidden bg-[var(--fill-tsp-white-main)] group/attach cursor-pointer flex-shrink-0"
    >
      {previewUrl ? (
        <img
          src={previewUrl}
          alt={file.filename}
          className="w-full h-full object-cover"
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-[var(--icon-tertiary)]">
          <Loader2 size={18} className="animate-spin" />
        </div>
      )}
      {uploading && (
        <div className="absolute inset-0 bg-black/40 flex items-center justify-center">
          <Loader2 size={18} className="animate-spin text-white" />
        </div>
      )}
      {failed && (
        <div className="absolute inset-0 bg-[var(--function-error)]/40 flex items-center justify-center text-[10px] text-white text-center px-1">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onRetry()
            }}
            className="flex items-center gap-1"
          >
            <RefreshCcw size={12} />
            <span>Retry</span>
          </button>
        </div>
      )}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          onRemove()
        }}
        className="hidden group-hover/attach:flex absolute top-1 right-1 rounded-full p-[3px] bg-black/60 hover:bg-black/80"
        title="Remove"
      >
        <X size={10} className="text-white" />
      </button>
    </div>
  )
}


export default ChatBoxFiles
