import { useEffect, useRef } from 'react'
// novnc 1.7+ exports RFB at the package root (`exports: "./core/rfb.js"`).
// @ts-expect-error no upstream types
import RFB from '@novnc/novnc'

import { getVNCUrl } from '@/api/agent'

interface RFBLike {
  disconnect: () => void
  viewOnly: boolean
  scaleViewport: boolean
  addEventListener: (event: string, handler: (e: unknown) => void) => void
}

interface Props {
  sessionId: string
  enabled?: boolean
  viewOnly?: boolean
  onConnected?: () => void
  onDisconnected?: (reason?: unknown) => void
  onCredentialsRequired?: () => void
}

export default function VNCViewer({
  sessionId,
  enabled = true,
  viewOnly = false,
  onConnected,
  onDisconnected,
  onCredentialsRequired,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const rfbRef = useRef<RFBLike | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!enabled || !container) return

    // StrictMode in dev runs effects twice. Track this run's RFB locally so
    // teardown only kills the instance it created, never one belonging to a
    // concurrent effect run.
    let cancelled = false
    let localRfb: RFBLike | null = null

    void (async () => {
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
          scaleViewport: true,
        })
        rfb.viewOnly = viewOnly
        rfb.scaleViewport = true
        rfb.addEventListener('connect', () => onConnected?.())
        rfb.addEventListener('disconnect', (e) => onDisconnected?.(e))
        rfb.addEventListener('credentialsrequired', () => onCredentialsRequired?.())

        if (cancelled) {
          rfb.disconnect()
          return
        }
        localRfb = rfb
        rfbRef.current = rfb
      } catch (e) {
        console.error('Failed to initialize VNC connection:', e)
      }
    })()

    return () => {
      cancelled = true
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
    // Callback identity intentionally excluded — the RFB-attached listeners
    // are stable for the life of one connection; we don't want to reconnect on
    // every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, enabled])

  useEffect(() => {
    if (rfbRef.current) rfbRef.current.viewOnly = viewOnly
  }, [viewOnly])

  return (
    <div
      ref={containerRef}
      className="vnc-container flex w-full h-full overflow-auto bg-[rgb(40,40,40)]"
    />
  )
}
