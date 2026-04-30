import { toast } from 'sonner'

type ToastType = 'error' | 'info' | 'success'

interface ToastOptions {
  message: string
  type?: ToastType
  duration?: number
}

export function showToast(options: ToastOptions | string): void {
  const config: ToastOptions = typeof options === 'string' ? { message: options } : options
  const duration = config.duration ?? 3000
  switch (config.type) {
    case 'error':
      toast.error(config.message, { duration })
      break
    case 'success':
      toast.success(config.message, { duration })
      break
    default:
      toast(config.message, { duration })
  }
}

export const showErrorToast = (message: string, duration?: number) =>
  showToast({ message, type: 'error', duration })

export const showInfoToast = (message: string, duration?: number) =>
  showToast({ message, type: 'info', duration })

export const showSuccessToast = (message: string, duration?: number) =>
  showToast({ message, type: 'success', duration })

declare global {
  interface Window {
    toast: {
      show: typeof showToast
      error: typeof showErrorToast
      info: typeof showInfoToast
      success: typeof showSuccessToast
    }
  }
}

if (typeof window !== 'undefined') {
  window.toast = {
    show: showToast,
    error: showErrorToast,
    info: showInfoToast,
    success: showSuccessToast,
  }
}
