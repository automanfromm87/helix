import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'

import * as bus from '@/lib/eventBus'
import VNCViewer from './VNCViewer'

type ConnState = 'connecting' | 'connected' | 'disconnected'

// Centralised z-index for full-screen modals. The literal stays on a
// single layer so future overlays (toast, lightbox, error banner) can
// either coexist or explicitly opt out of being above takeover.
const TAKEOVER_Z = 100

/** Full-screen VNC interactive overlay activated via the global "takeover" event. */
export default function TakeOverView() {
  const [active, setActive] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [conn, setConn] = useState<ConnState>('connecting')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const location = useLocation()

  const exit = useCallback(() => {
    setActive(false)
    setSessionId(null)
    setErrorMsg(null)
  }, [])

  useEffect(() => {
    return bus.on('takeover', (detail) => {
      if (detail.active) {
        setSessionId(detail.sessionId)
        setActive(true)
        setConn('connecting')
        setErrorMsg(null)
      } else {
        exit()
      }
    })
  }, [exit])

  // Auto-dismiss when the user navigates away — the takeover overlay is
  // tied to the session in the URL; staying open with a stale sessionId
  // would just confuse the user when they're already on a different chat.
  useEffect(() => {
    if (active) exit()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname])

  // ESC closes — fullscreen overlay UX expectation. Bound at window level
  // so it works regardless of whether the inner container has focus.
  useEffect(() => {
    if (!active) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') exit()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [active, exit])

  // On open, focus the container so keyboard input routes to novnc's
  // canvas immediately (the user shouldn't have to click first).
  useEffect(() => {
    if (active && conn === 'connected') containerRef.current?.focus()
  }, [active, conn])

  if (!active || !sessionId) return null

  return (
    <div
      className="fixed inset-0 bg-black/85 flex flex-col"
      style={{ zIndex: TAKEOVER_Z }}
    >
      <div className="flex items-center justify-between px-4 h-12 bg-black text-white">
        <div className="flex items-center gap-2">
          <span className="text-sm">Live Browser Takeover</span>
          <span
            className={
              conn === 'connected'
                ? 'text-xs text-green-400'
                : conn === 'connecting'
                  ? 'text-xs text-yellow-300'
                  : 'text-xs text-red-400'
            }
          >
            ({conn})
          </span>
          <span className="text-[11px] text-white/60 ml-2">ESC to exit</span>
        </div>
        <button
          type="button"
          onClick={exit}
          className="text-sm px-3 h-8 rounded-md bg-white/10 hover:bg-white/20"
        >
          Exit Takeover
        </button>
      </div>
      <div ref={containerRef} className="flex-1 min-h-0 relative outline-none" tabIndex={-1}>
        <VNCViewer
          sessionId={sessionId}
          enabled
          viewOnly={false}
          clipboardSync
          onConnected={() => setConn('connected')}
          onDisconnected={(reason) => {
            setConn('disconnected')
            // novnc disconnect events surface the underlying reason in
            // `event.detail.reason` — show it so a black screen is explained.
            const detail = (reason as { detail?: { reason?: string } })?.detail?.reason
            if (detail) setErrorMsg(detail)
          }}
        />
        {conn !== 'connected' && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="text-white text-sm bg-black/60 rounded-md px-4 py-2">
              {conn === 'connecting' && 'Connecting to sandbox VNC…'}
              {conn === 'disconnected' && (errorMsg ? `Disconnected: ${errorMsg}` : 'Disconnected from sandbox')}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
