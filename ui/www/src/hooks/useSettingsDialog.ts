import { create } from 'zustand'

interface SettingsDialogStore {
  isOpen: boolean
  defaultTab: string
  openSettingsDialog: (tabId?: string) => void
  closeSettingsDialog: () => void
  toggleSettingsDialog: () => void
  setDefaultTab: (tabId: string) => void
}

export const useSettingsDialog = create<SettingsDialogStore>((set, get) => ({
  isOpen: false,
  defaultTab: 'settings',
  openSettingsDialog: (tabId) => set({ isOpen: true, defaultTab: tabId ?? get().defaultTab }),
  closeSettingsDialog: () => set({ isOpen: false }),
  toggleSettingsDialog: () => set({ isOpen: !get().isOpen }),
  setDefaultTab: (tabId) => set({ defaultTab: tabId }),
}))
