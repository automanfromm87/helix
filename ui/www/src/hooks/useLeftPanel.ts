import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

interface LeftPanelStore {
  isLeftPanelShow: boolean
  toggleLeftPanel: () => void
  setLeftPanel: (visible: boolean) => void
  showLeftPanel: () => void
  hideLeftPanel: () => void
}

export const useLeftPanel = create<LeftPanelStore>()(
  persist(
    (set, get) => ({
      isLeftPanelShow: false,
      toggleLeftPanel: () => set({ isLeftPanelShow: !get().isLeftPanelShow }),
      setLeftPanel: (visible) => set({ isLeftPanelShow: visible }),
      showLeftPanel: () => set({ isLeftPanelShow: true }),
      hideLeftPanel: () => set({ isLeftPanelShow: false }),
    }),
    {
      name: 'helix-left-panel-state',
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({ isLeftPanelShow: s.isLeftPanelShow }),
    },
  ),
)
