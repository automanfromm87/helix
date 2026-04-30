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
  const { visible, config, hide, handleConfirm, handleCancel } = useDialog()

  return (
    <Dialog open={visible} onOpenChange={(open) => (open ? null : hide())}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{config.title}</DialogTitle>
          <DialogDescription>{config.content}</DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2">
          <button
            onClick={handleCancel}
            className="px-3 h-9 rounded-md border border-[var(--border-btn-main)] bg-transparent hover:bg-[var(--fill-tsp-white-light)] text-sm font-medium"
          >
            {config.cancelText}
          </button>
          <button
            onClick={handleConfirm}
            className={cn(
              'px-3 h-9 rounded-md text-sm font-medium text-[var(--text-onblack)]',
              config.confirmType === 'danger'
                ? 'bg-[var(--function-error)] hover:opacity-90'
                : 'bg-[var(--Button-primary-black)] hover:opacity-90',
            )}
          >
            {config.confirmText}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
