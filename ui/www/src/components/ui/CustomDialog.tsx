import { useDialog } from '@/hooks/useDialog'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from './Dialog'
import { cn } from '@/lib/utils'

/** Globally-mounted confirm dialog driven by useDialog store. */
export default function CustomDialog() {
  const { visible, pending, config, hide, handleConfirm, handleCancel } =
    useDialog()

  return (
    <Dialog
      open={visible}
      onOpenChange={(open) => {
        // Block close-via-escape / outside-click while pending so the
        // dialog stays put until the in-flight callback finishes.
        if (open || pending) return
        hide()
      }}
    >
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{config.title}</DialogTitle>
          <DialogDescription>{config.content}</DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2">
          <button
            onClick={handleCancel}
            disabled={pending}
            className="px-3 h-9 rounded-md border border-[var(--border-btn-main)] bg-transparent hover:bg-[var(--fill-tsp-white-light)] text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {config.cancelText}
          </button>
          <button
            onClick={handleConfirm}
            disabled={pending}
            className={cn(
              'px-3 h-9 rounded-md text-sm font-medium text-[var(--text-onblack)]',
              'disabled:opacity-50 disabled:cursor-not-allowed',
              config.confirmType === 'danger'
                ? 'bg-[var(--function-error)] hover:opacity-90'
                : 'bg-[var(--Button-primary-black)] hover:opacity-90',
            )}
          >
            {pending ? 'Working…' : config.confirmText}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
