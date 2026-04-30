import { create } from 'zustand'

interface SessionFileListStore {
  visible: boolean
  shared: boolean
  showSessionFileList: (shared?: boolean) => void
  hideSessionFileList: () => void
}

export const useSessionFileList = create<SessionFileListStore>((set) => ({
  visible: false,
  shared: false,
  showSessionFileList: (shared = false) => set({ visible: true, shared }),
  hideSessionFileList: () => set({ visible: false }),
}))
