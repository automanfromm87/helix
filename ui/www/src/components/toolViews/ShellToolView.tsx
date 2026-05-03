import { useEffect, useRef, useState } from 'react'

import { getShellStreamUrl } from '@/api/agent'
import type { ToolViewProps } from '@/constants/tool'

/**
 * Shell tool view — always renders an interactive xterm.js terminal.
 *
 * Each mount opens a brand-new pty in the sandbox over a WebSocket. We
 * intentionally don't try to "replay" the historical command + output the
 * agent captured: that data is already shown inline in the chat (as the
 * tool result), and the side panel's job is to give the user a place to
 * drive the shell themselves. Reopening the panel always gives a fresh
 * shell rather than trying to splice into an old one.
 *
 * The `live` prop is no longer load-bearing — kept in the signature to
 * match the ToolViewProps contract, but dropping into a fresh pty is the
 * right behavior whether the underlying tool was just-called or
 * historical.
 */
export default function ShellToolView({ sessionId }: ToolViewProps) {
  return <InteractiveTerminal sessionId={sessionId} />
}

// ---------------------------------------------------------------------------
// Interactive xterm.js pty over WebSocket
// ---------------------------------------------------------------------------

/** Heartbeat interval; if no message + no successful send happens within this
 * window we treat the socket as wedged and force a reconnect. Matches the
 * 90s SSE idle timeout — same class of "TCP half-open / proxy buffer stuck"
 * failure mode. */
const IDLE_TIMEOUT_MS = 90_000
/** Cap retries so a fundamentally broken sandbox doesn't loop forever. */
const MAX_RETRIES = 2
/** Delay before reconnecting; multiplied by the attempt number. */
const RETRY_DELAY_MS = 1500

function InteractiveTerminal({ sessionId }: { sessionId: string }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<'connecting' | 'open' | 'closed'>('connecting')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    let cancelled = false
    let ws: WebSocket | null = null
    type TerminalLike = {
      open: (el: HTMLElement) => void
      onData: (cb: (data: string) => void) => void
      write: (data: string | Uint8Array) => void
      cols: number
      rows: number
      dispose: () => void
    }
    type FitLike = { fit: () => void }
    let term: TerminalLike | null = null
    let fit: FitLike | null = null
    let resizeObserver: ResizeObserver | null = null
    let idleTimer: number | null = null
    let retryTimer: number | null = null
    let attempt = 0

    const armIdle = () => {
      if (idleTimer !== null) window.clearTimeout(idleTimer)
      idleTimer = window.setTimeout(() => {
        // Force-close the wedged socket so onclose runs the retry path.
        if (ws && ws.readyState !== WebSocket.CLOSED) {
          try {
            ws.close()
          } catch {
            /* ignore */
          }
        }
      }, IDLE_TIMEOUT_MS)
    }

    const connect = async () => {
      let url: string
      try {
        url = await getShellStreamUrl(sessionId)
      } catch (e) {
        if (!cancelled) {
          setStatus('closed')
          setErrorMsg(`Failed to open terminal: ${(e as Error).message}`)
        }
        return
      }
      if (cancelled) return

      ws = new WebSocket(url)
      ws.binaryType = 'arraybuffer'

      ws.onopen = () => {
        attempt = 0
        setStatus('open')
        setErrorMsg(null)
        armIdle()
        if (term) {
          try {
            ws?.send(
              JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }),
            )
          } catch {
            /* ignore — onerror will fire if the socket is broken */
          }
        }
      }
      ws.onmessage = (ev) => {
        armIdle()
        if (!term) return
        if (ev.data instanceof ArrayBuffer) {
          // xterm.js write accepts Uint8Array directly — UTF-8 decoding
          // happens internally with proper handling of partial sequences
          // across chunk boundaries.
          term.write(new Uint8Array(ev.data))
        } else if (typeof ev.data === 'string') {
          // Server-side JSON status frames (errors, ready) come as text.
          // We just print them in red so the user sees what happened.
          term.write(`\x1b[31m${ev.data}\x1b[0m\r\n`)
        }
      }
      ws.onclose = (ev) => {
        if (idleTimer !== null) window.clearTimeout(idleTimer)
        if (cancelled) return
        if (ev.reason) setErrorMsg(ev.reason)
        if (attempt < MAX_RETRIES) {
          attempt++
          setStatus('connecting')
          retryTimer = window.setTimeout(() => {
            if (!cancelled) void connect()
          }, RETRY_DELAY_MS * attempt)
        } else {
          setStatus('closed')
        }
      }
      ws.onerror = () => {
        // Browsers don't surface a useful detail on WS errors, so show a
        // generic placeholder. Critically, also flip status — the prior
        // version left the badge stuck on green when the socket died via
        // onerror without a follow-up onclose.
        if (cancelled) return
        setErrorMsg((prev) => prev ?? 'WebSocket error')
        setStatus('closed')
      }
    }

    void (async () => {
      // Lazy-load so the xterm bundle (≈400KB) doesn't ship with the
      // initial chunk for users who never open the terminal panel.
      const [{ Terminal }, { FitAddon }] = await Promise.all([
        import('@xterm/xterm'),
        import('@xterm/addon-fit'),
      ])
      // xterm's CSS is mandatory — without it the canvas-less DOM
      // renderer paints onto a 0px-tall element. Side-effect import is
      // tree-shaker safe under Vite.
      await import('@xterm/xterm/css/xterm.css')

      if (cancelled) return

      term = new Terminal({
        cursorBlink: true,
        fontFamily:
          'ui-monospace, SFMono-Regular, Menlo, Monaco, "Roboto Mono", "Courier New", monospace',
        fontSize: 13,
        scrollback: 5000,
        theme: { background: '#1e1e1e', foreground: '#e8e8e8' },
      }) as unknown as TerminalLike
      fit = new FitAddon() as unknown as FitLike
      ;(term as unknown as { loadAddon: (a: unknown) => void }).loadAddon(fit)
      term.open(container)

      try {
        fit.fit()
      } catch {
        /* fit may throw on very small containers; harmless */
      }

      term.onData((data: string) => {
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(data)
      })

      // Propagate panel resizes to the pty. Debounce — a user dragging
      // the divider can fire dozens of resize events per second; the pty
      // doesn't need them all and the sandbox has to allocate a TIOCSWINSZ
      // for each.
      let resizeTimer: number | null = null
      resizeObserver = new ResizeObserver(() => {
        if (resizeTimer !== null) window.clearTimeout(resizeTimer)
        resizeTimer = window.setTimeout(() => {
          if (!fit || !term || !ws || ws.readyState !== WebSocket.OPEN) return
          try {
            fit.fit()
            ws.send(
              JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }),
            )
          } catch {
            /* fit can throw on a hidden panel */
          }
        }, 150)
      })
      resizeObserver.observe(container)

      void connect()
    })()

    return () => {
      cancelled = true
      if (idleTimer !== null) window.clearTimeout(idleTimer)
      if (retryTimer !== null) window.clearTimeout(retryTimer)
      if (resizeObserver) resizeObserver.disconnect()
      if (ws) {
        try {
          ws.close()
        } catch {
          /* ignore */
        }
      }
      if (term) {
        try {
          term.dispose()
        } catch {
          /* ignore */
        }
      }
    }
  }, [sessionId])

  return (
    <div className="flex flex-col h-full w-full bg-[#1e1e1e]">
      <div className="h-[36px] flex items-center justify-between px-3 border-b border-[var(--border-main)]">
        <div className="text-[var(--text-tertiary)] text-sm font-medium">Terminal</div>
        <div className="text-[11px] uppercase tracking-wide">
          {status === 'connecting' && (
            <span className="text-yellow-400">connecting…</span>
          )}
          {status === 'open' && <span className="text-green-400">connected</span>}
          {status === 'closed' && <span className="text-red-400">disconnected</span>}
        </div>
      </div>
      <div className="relative flex-1 min-h-0">
        <div ref={containerRef} className="absolute inset-0 px-2 py-2" />
        {errorMsg && status === 'closed' && (
          <div className="absolute top-2 right-2 text-[12px] text-red-300 bg-black/40 px-2 py-1 rounded">
            {errorMsg}
          </div>
        )}
      </div>
    </div>
  )
}
