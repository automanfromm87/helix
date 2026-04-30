import { Toaster as Sonner } from 'sonner'

export function Toaster() {
  return (
    <Sonner
      position="top-center"
      toastOptions={{
        classNames: {
          toast:
            'rounded-xl border border-[var(--border-light)] bg-[var(--background-menu-white)] text-[var(--text-primary)] shadow-[0px_8px_32px_0px_var(--shadow-S)]',
          description: 'text-[var(--text-tertiary)]',
        },
      }}
    />
  )
}
