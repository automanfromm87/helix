import { useEffect, useState } from 'react'

import VNCViewer from './VNCViewer'

interface TakeoverDetail {
  sessionId: string
  active: boolean
}

type ConnState = 'connecting' | 'connected' | 'disconnected'

/** Full-screen VNC interactive overlay activated via the global "takeover" event. */
export default function TakeOverView() {
  const [active, setActive] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [conn, setConn] = useState<ConnState>('connecting')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<TakeoverDetail>).detail
      if (!detail) return
      if (detail.active) {
        setSessionId(detail.sessionId)
        setActive(true)
        setConn('connecting')
        setErrorMsg(null)
      } else {
        setActive(false)
      }
    }
    window.addEventListener('takeover', handler as EventListener)
    return () => window.removeEventListener('takeover', handler as EventListener)
  }, [])

  if (!active || !sessionId) return null

  return (
    <div className="fixed inset-0 z-[100] bg-black/85 flex flex-col">
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
        </div>
        <button
          type="button"
          onClick={() => setActive(false)}
          className="text-sm px-3 h-8 rounded-md bg-white/10 hover:bg-white/20"
        >
          Exit Takeover
        </button>
      </div>
      <div className="flex-1 min-h-0 relative">
        <VNCViewer
          sessionId={sessionId}
          enabled
          viewOnly={false}
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
