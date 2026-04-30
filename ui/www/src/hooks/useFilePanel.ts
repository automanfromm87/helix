import { create } from 'zustand'
import type { FileInfo } from '@/api/file'
import { eventBus } from '@/utils/eventBus'
import { EVENT_SHOW_FILE_PANEL } from '@/constants/event'

interface FilePanelStore {
  isShow: boolean
  visible: boolean
  fileInfo?: FileInfo
  showFilePanel: (file: FileInfo) => void
  hideFilePanel: () => void
  setVisible: (v: boolean) => void
}

export const useFilePanel = create<FilePanelStore>((set) => ({
  isShow: false,
  visible: true,
  fileInfo: undefined,
  showFilePanel: (file) => {
    eventBus.emit(EVENT_SHOW_FILE_PANEL)
    set({ isShow: true, visible: true, fileInfo: file })
  },
  hideFilePanel: () => set({ isShow: false }),
  setVisible: (visible) => set({ visible }),
}))
