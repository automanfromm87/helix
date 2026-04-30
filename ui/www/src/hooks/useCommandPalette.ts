import { create } from 'zustand'

interface CommandPaletteStore {
  visible: boolean
  open: () => void
  close: () => void
  toggle: () => void
}

export const useCommandPalette = create<CommandPaletteStore>((set, get) => ({
  visible: false,
  open: () => set({ visible: true }),
  close: () => set({ visible: false }),
  toggle: () => set({ visible: !get().visible }),
}))
