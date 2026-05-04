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
  /** True while `handleConfirm` is awaiting an async `onConfirm`. The
   * dialog button reads this to render a disabled / spinner state so a
   * second click during a slow network round-trip can't fire the
   * callback twice (the original "click delete twice to delete" bug). */
  pending: boolean
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
  pending: false,
  config: defaultConfig,
  showConfirmDialog: (options) => {
    set({
      visible: true,
      pending: false,
      config: {
        ...defaultConfig,
        ...options,
        confirmText: options.confirmText ?? 'Confirm',
        cancelText: options.cancelText ?? 'Cancel',
        confirmType: options.confirmType ?? 'primary',
      },
    })
  },
  hide: () => set({ visible: false, pending: false }),
  handleConfirm: async () => {
    // Re-entry guard: ignore extra clicks while the prior callback is
    // still awaiting. Without this, an async onConfirm (delete project /
    // delete chat / etc.) fires once per click during the network round-
    // trip — the user perceives it as "had to click twice", and the
    // backend sees a duplicate request that 404s on the second attempt.
    if (get().pending) return
    set({ pending: true })
    try {
      const cb = get().config.onConfirm
      if (cb) await cb()
    } finally {
      set({ visible: false, pending: false })
    }
  },
  handleCancel: () => {
    // Don't allow cancel while pending either — the in-flight callback
    // is past the point of caring about user intent.
    if (get().pending) return
    const cb = get().config.onCancel
    cb?.()
    set({ visible: false })
  },
}))
