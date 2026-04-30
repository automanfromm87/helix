import { create } from 'zustand'
import type { ToolContent } from '@/types/message'
import type { FileInfo } from '@/api/file'

interface RightPanelStore {
  isShow: boolean
  live: boolean
  toolContent?: ToolContent
  fileInfo?: FileInfo
  panelType: 'tool' | 'file'
  showTool: (content: ToolContent, isLive?: boolean) => void
  showFile: (file: FileInfo) => void
  hide: () => void
}

export const useRightPanel = create<RightPanelStore>((set) => ({
  isShow: false,
  live: false,
  toolContent: undefined,
  fileInfo: undefined,
  panelType: 'tool',
  showTool: (content, isLive = false) =>
    set({ panelType: 'tool', toolContent: content, isShow: true, live: isLive }),
  showFile: (file) => set({ panelType: 'file', fileInfo: file, isShow: true }),
  hide: () => set({ isShow: false }),
}))
