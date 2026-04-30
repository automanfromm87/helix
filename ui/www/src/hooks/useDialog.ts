import { create } from 'zustand'

export interface ConfirmDialogConfig {
  title: string
  content: string
  confirmText?: string
  cancelText?: string
  confirmType?: 'primary' | 'danger'
  onConfirm?: () => void | Promise<void>
  onCancel?: () => void
}

interface DialogStore {
  visible: boolean
  config: Required<Omit<ConfirmDialogConfig, 'onConfirm' | 'onCancel'>> & {
    onConfirm?: () => void | Promise<void>
    onCancel?: () => void
  }
  showConfirmDialog: (options: ConfirmDialogConfig) => void
  hide: () => void
  handleConfirm: () => Promise<void>
  handleCancel: () => void
}

const defaultConfig = {
  title: '',
  content: '',
  confirmText: 'Confirm',
  cancelText: 'Cancel',
  confirmType: 'primary' as const,
  onConfirm: undefined,
  onCancel: undefined,
}

export const useDialog = create<DialogStore>((set, get) => ({
  visible: false,
  config: defaultConfig,
  showConfirmDialog: (options) => {
    set({
      visible: true,
      config: {
        ...defaultConfig,
        ...options,
        confirmText: options.confirmText ?? 'Confirm',
        cancelText: options.cancelText ?? 'Cancel',
        confirmType: options.confirmType ?? 'primary',
      },
    })
  },
  hide: () => set({ visible: false }),
  handleConfirm: async () => {
    const cb = get().config.onConfirm
    if (cb) await cb()
    set({ visible: false })
  },
  handleCancel: () => {
    const cb = get().config.onCancel
    cb?.()
    set({ visible: false })
  },
}))
