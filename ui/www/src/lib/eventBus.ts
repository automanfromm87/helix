import type { InspectorPayload } from '@/components/toolViews/PreviewToolView'

/**
 * Typed event bus over `window`. Events flow between widely-separated
 * modules where lifting state to a common parent is awkward (e.g. the
 * iframe-hosted PreviewToolView posting selections up to ChatPage).
 *
 * Centralised so:
 *   - Names live in one place — typos surface as TS errors instead of
 *     silently dead listeners.
 *   - Payload shapes are tied to the name in `EventMap` so each end
 *     agrees on the contract.
 *   - Code review can grep one file to see who emits/listens to what.
 *
 * Underlying transport is still `CustomEvent` on `window`, so existing
 * outside-React listeners (or browser dev tools) keep working.
 */

export interface EventMap {
  /** PreviewToolView → ChatPage: user clicked an inspected element. */
  'helix:preview:select': InspectorPayload
  /** ToolUse option button → ChatPage: user picked an option-reply text. */
  'helix:reply-with-option': string
  /** axios interceptor → useAuth: refresh failed, force logout state. */
  'auth:logout': undefined
  /** axios interceptor / SSE driver → app: a new access token is in flight. */
  'auth:token-refreshed': undefined
  /** BrowserToolView → TakeOverView: a sandbox browser asks for takeover. */
  takeover: { sessionId: string; active: boolean }
}

type EventName = keyof EventMap

export function emit<K extends EventName>(name: K, detail: EventMap[K]): void {
  window.dispatchEvent(new CustomEvent(name, { detail }))
}

export function on<K extends EventName>(
  name: K,
  handler: (detail: EventMap[K]) => void,
): () => void {
  const listener = (e: Event) => {
    handler((e as CustomEvent<EventMap[K]>).detail)
  }
  window.addEventListener(name, listener)
  return () => window.removeEventListener(name, listener)
}
