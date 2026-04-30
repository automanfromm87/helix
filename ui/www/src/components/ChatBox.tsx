import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react'
import { Paperclip } from 'lucide-react'

import type { FileInfo } from '@/api/file'
import { SendIcon } from '@/components/icons'
import ChatBoxFiles, { type ChatBoxFilesHandle } from './ChatBoxFiles'
import { cn } from '@/lib/utils'

interface Props {
  value: string
  onChange: (value: string) => void
  rows: number
  isRunning: boolean
  attachments: FileInfo[]
  onAttachmentsChange?: (files: FileInfo[]) => void
  onSubmit: () => void
  onStop?: () => void
  hideStopButton?: boolean
  allowSendFilesOnly?: boolean
}

export interface ChatBoxHandle {
  uploadFile: () => void
  isAllUploaded: () => boolean
}

const ChatBox = forwardRef<ChatBoxHandle, Props>(
  (
    {
      value,
      onChange,
      rows,
      isRunning,
      attachments,
      onAttachmentsChange,
      onSubmit,
      onStop,
      hideStopButton,
      allowSendFilesOnly,
    },
    ref,
  ) => {
    const [isComposing, setIsComposing] = useState(false)
    const filesRef = useRef<ChatBoxFilesHandle>(null)
    const hasTextInput = value.trim() !== ''

    const sendEnabled = useMemo(() => {
      const hasFiles = (attachments?.length ?? 0) > 0
      const allUploaded = filesRef.current?.isAllUploaded() ?? true
      if (allowSendFilesOnly) return hasTextInput || (hasFiles && allUploaded)
      return hasTextInput && (!hasFiles || allUploaded)
    }, [hasTextInput, attachments, allowSendFilesOnly])

    useImperativeHandle(ref, () => ({
      uploadFile: () => filesRef.current?.uploadFile(),
      isAllUploaded: () => filesRef.current?.isAllUploaded() ?? true,
    }))

    const handleEnter = (event: KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key !== 'Enter') return
      if (event.shiftKey || isComposing) return
      if (sendEnabled) {
        event.preventDefault()
        onSubmit()
      }
    }

    // Force re-render when filesRef state may have changed (its uploads are async).
    const [, force] = useState(0)
    useEffect(() => {
      const id = window.setInterval(() => force((x) => x + 1), 500)
      return () => window.clearInterval(id)
    }, [])

    return (
      <div className="pb-3 relative bg-[var(--background-gray-main)]">
        <div className="flex flex-col gap-3 rounded-[22px] transition-all relative bg-[var(--fill-input-chat)] py-3 max-h-[300px] shadow-[0px_12px_32px_0px_rgba(0,0,0,0.02)] border border-black/8 dark:border-[var(--border-main)]">
          <ChatBoxFiles
            ref={filesRef}
            attachments={attachments}
            onChange={onAttachmentsChange}
          />
          <div className="overflow-y-auto pl-4 pr-2">
            <textarea
              className="flex rounded-md border-input focus-visible:outline-none focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 overflow-hidden flex-1 bg-transparent p-0 pt-[1px] border-0 focus-visible:ring-0 focus-visible:ring-offset-0 w-full placeholder:text-[var(--text-disable)] text-[15px] shadow-none resize-none min-h-[40px]"
              rows={rows}
              value={value}
              onChange={(e) => onChange(e.target.value)}
              onCompositionStart={() => setIsComposing(true)}
              onCompositionEnd={() => setIsComposing(false)}
              onKeyDown={handleEnter}
              placeholder="Give Helix a task to work on..."
              style={{ height: '46px' }}
            />
          </div>
          <footer className="flex flex-row justify-between w-full px-3">
            <div className="flex gap-2 pr-2 items-center">
              <button
                onClick={() => filesRef.current?.uploadFile()}
                className="rounded-full border border-[var(--border-main)] inline-flex items-center justify-center gap-1 cursor-pointer text-xs text-[var(--text-secondary)] hover:bg-[var(--fill-tsp-gray-main)] w-8 h-8 p-0 shrink-0"
              >
                <Paperclip size={16} />
              </button>
            </div>
            <div className="flex gap-2">
              {!isRunning || sendEnabled || hideStopButton ? (
                <button
                  className={cn(
                    'whitespace-nowrap text-sm font-medium p-0 w-8 h-8 rounded-full flex items-center justify-center transition-colors hover:opacity-90',
                    !sendEnabled
                      ? 'cursor-not-allowed bg-[var(--fill-tsp-white-dark)]'
                      : 'cursor-pointer bg-[var(--Button-primary-black)]',
                  )}
                  onClick={() => sendEnabled && onSubmit()}
                  disabled={!sendEnabled}
                >
                  <SendIcon disabled={!sendEnabled} />
                </button>
              ) : (
                !hideStopButton && (
                  <button
                    onClick={() => onStop?.()}
                    className="inline-flex items-center justify-center whitespace-nowrap text-sm font-medium bg-[var(--Button-primary-black)] text-[var(--text-onblack)] hover:opacity-90 rounded-full p-0 w-8 h-8"
                  >
                    <div className="w-[10px] h-[10px] bg-[var(--icon-onblack)] rounded-[2px]" />
                  </button>
                )
              )}
            </div>
          </footer>
        </div>
      </div>
    )
  },
)

ChatBox.displayName = 'ChatBox'

export default ChatBox
