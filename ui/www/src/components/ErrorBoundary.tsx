import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  /** Tag for log output so you can tell which boundary caught it. */
  scope?: string
  children: ReactNode
  fallback?: (error: Error, reset: () => void) => ReactNode
}

interface State {
  error: Error | null
}

/**
 * Page-level error boundary. Without it, any throw inside a ChatMessage /
 * markdown renderer / virtualizer subtree blanks the entire app — the
 * "white screen of death" pattern. We surface the error and let the user
 * retry the affected subtree without reloading the page.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[ErrorBoundary${this.props.scope ? `:${this.props.scope}` : ''}]`, error, info)
  }

  reset = () => this.setState({ error: null })

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    if (this.props.fallback) return this.props.fallback(error, this.reset)
    return (
      <div className="flex flex-col items-center justify-center h-full w-full p-8 gap-4">
        <div className="text-[var(--text-primary)] text-lg font-medium">
          Something went wrong
        </div>
        <pre className="text-sm text-[var(--text-tertiary)] max-w-lg whitespace-pre-wrap text-center">
          {error.message}
        </pre>
        <button
          onClick={this.reset}
          className="h-9 px-4 rounded-full bg-[var(--Button-primary-black)] text-[var(--text-onblack)] text-sm font-medium hover:opacity-90"
        >
          Try again
        </button>
      </div>
    )
  }
}
