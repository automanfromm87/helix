interface Props {
  text?: string
}

export default function LoadingIndicator({ text = 'Loading' }: Props) {
  return (
    <div className="flex items-center gap-2 text-[var(--text-tertiary)] py-2">
      <div className="flex gap-1">
        <span className="size-1.5 rounded-full bg-current animate-pulse [animation-delay:0ms]" />
        <span className="size-1.5 rounded-full bg-current animate-pulse [animation-delay:150ms]" />
        <span className="size-1.5 rounded-full bg-current animate-pulse [animation-delay:300ms]" />
      </div>
      <span className="text-sm">{text}</span>
    </div>
  )
}
