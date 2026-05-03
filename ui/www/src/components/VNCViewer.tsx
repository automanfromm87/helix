import { useEffect, useRef } from 'react'
import RFB from '@novnc/novnc'

import { getVNCUrl } from '@/api/agent'

// Locally narrow the RFB type to the surface VNCViewer touches, so the
// rest of the component reads cleanly even though our shipping .d.ts is
// minimal. (Types live in src/types/novnc.d.ts.)
type RFBLike = InstanceType<typeof RFB>

interface Props {
  sessionId: string
  enabled?: boolean
  viewOnly?: boolean
  /**
   * On transient disconnects (server reset, brief network blip), retry the
   * connection up to this many times with a short backoff. 0 disables
   * retry entirely. Defaults to 2 — enough to ride out a sandbox restart
   * without leaving the user staring at a red banner.
   */
  maxRetries?: number
  /**
   * When true, sync clipboard text in both directions: text copied inside
   * the VNC session lands in the host clipboard, and paste events on the
   * viewer get forwarded into the sandbox. Default false (browsers gate
   * clipboard API behind permissions, only enable when the user actually
   * wants interactive control).
   */
  clipboardSync?: boolean
  onConnected?: () => void
  onDisconnected?: (reason?: unknown) => void
  onCredentialsRequired?: () => void
}

const RETRY_DELAY_MS = 1500

export default function VNCViewer({
  sessionId,
  enabled = true,
  viewOnly = false,
  maxRetries = 2,
  clipboardSync = false,
  onConnected,
  onDisconnected,
  onCredentialsRequired,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const rfbRef = useRef<RFBLike | null>(null)

  // Mirror the latest callbacks behind a ref so RFB listeners (which are
  // attached once for the life of the connection) always invoke the most
  // recent closure passed by the parent. Without this, parents that pass
  // inline arrow callbacks captured stale state from the first mount.
  const callbacksRef = useRef({ onConnected, onDisconnected, onCredentialsRequired })
  useEffect(() => {
    callbacksRef.current = { onConnected, onDisconnected, onCredentialsRequired }
  }, [onConnected, onDisconnected, onCredentialsRequired])

  useEffect(() => {
    const container = containerRef.current
    if (!enabled || !container) return

    let cancelled = false
    let localRfb: RFBLike | null = null
    let retryTimer: number | null = null
    let attempt = 0

    const connect = async () => {
      try {
        const wsUrl = await getVNCUrl(sessionId)
        if (cancelled) return

        // RFB renders into a canvas inside the container that survives
        // `disconnect()`. Wipe leftovers so a re-init doesn't draw a second one.
        while (container.firstChild) container.removeChild(container.firstChild)

        const rfb: RFBLike = new RFB(container, wsUrl, {
          credentials: { password: '' },
          shared: true,
          repeaterID: '',
          wsProtocols: ['binary'],
        })
        rfb.viewOnly = viewOnly
        rfb.scaleViewport = true
        rfb.addEventListener('connect', () => {
          attempt = 0
          callbacksRef.current.onConnected?.()
        })
        rfb.addEventListener('disconnect', (e) => {
          callbacksRef.current.onDisconnected?.(e)
          // Retry only when the parent didn't tear us down. RFB-emitted
          // disconnects with no detail are usually transient (proxy reset,
          // sandbox restart) and worth a couple of cheap retries.
          if (cancelled) return
          if (attempt < maxRetries) {
            attempt++
            retryTimer = window.setTimeout(() => {
              if (!cancelled) void connect()
            }, RETRY_DELAY_MS * attempt)
          }
        })
        rfb.addEventListener('credentialsrequired', () => {
          callbacksRef.current.onCredentialsRequired?.()
        })
        if (clipboardSync) {
          // Sandbox → host: write text the agent copied inside VNC into
          // the user's clipboard. Failures are non-fatal (browsers may
          // block clipboard write outside a user gesture; we log and
          // move on).
          rfb.addEventListener('clipboard', (e) => {
            const text = (e as { detail?: { text?: string } }).detail?.text
            if (typeof text === 'string' && text.length > 0) {
              navigator.clipboard?.writeText(text).catch(() => {/* non-fatal */})
            }
          })
        }

        if (cancelled) {
          rfb.disconnect()
          return
        }
        localRfb = rfb
        rfbRef.current = rfb
      } catch (e) {
        console.error('Failed to initialize VNC connection:', e)
        if (cancelled) return
        if (attempt < maxRetries) {
          attempt++
          retryTimer = window.setTimeout(() => {
            if (!cancelled) void connect()
          }, RETRY_DELAY_MS * attempt)
        } else {
          callbacksRef.current.onDisconnected?.(e)
        }
      }
    }

    void connect()

    return () => {
      cancelled = true
      if (retryTimer !== null) window.clearTimeout(retryTimer)
      if (localRfb) {
        try {
          localRfb.disconnect()
        } catch {
          // ignore
        }
        if (rfbRef.current === localRfb) rfbRef.current = null
      }
      while (container.firstChild) container.removeChild(container.firstChild)
    }
  }, [sessionId, enabled, maxRetries, viewOnly, clipboardSync])

  // Host → sandbox: forward paste events on the viewer into the VNC
  // clipboard so cmd-V works. Only wired when clipboard sync is on.
  useEffect(() => {
    if (!clipboardSync) return
    const el = containerRef.current
    if (!el) return
    const onPaste = (e: ClipboardEvent) => {
      const text = e.clipboardData?.getData('text/plain') ?? ''
      if (text && rfbRef.current?.clipboardPasteFrom) {
        e.preventDefault()
        rfbRef.current.clipboardPasteFrom(text)
      }
    }
    el.addEventListener('paste', onPaste)
    return () => el.removeEventListener('paste', onPaste)
  }, [clipboardSync])

  useEffect(() => {
    if (rfbRef.current) rfbRef.current.viewOnly = viewOnly
  }, [viewOnly])

  return (
    <div
      ref={containerRef}
      // tabIndex makes the container focusable so keyboard events route to
      // the inner novnc canvas. Without it, interactive (viewOnly=false)
      // sessions silently swallow keystrokes until the user clicks the
      // canvas itself.
      tabIndex={viewOnly ? -1 : 0}
      className="vnc-container flex w-full h-full overflow-auto bg-[rgb(40,40,40)] outline-none"
    />
  )
}

