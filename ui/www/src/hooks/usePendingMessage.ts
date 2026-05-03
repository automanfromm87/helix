import { create } from 'zustand'

import type { FileInfo } from '@/api/file'

interface PendingMessage {
  sessionId: string
  message: string
  files: FileInfo[]
}

interface PendingMessageStore {
  pending: PendingMessage | null
  /** HomePage stages a message and navigates to /chat/<sessionId>. */
  set: (pending: PendingMessage) => void
  /** ChatPage takes the message exactly once for a given session, then clears it. */
  take: (sessionId: string) => PendingMessage | null
  clear: () => void
}

/**
 * Cross-route handoff for the user's first message on a brand-new chat.
 *
 * Previously this used `react-router`'s `location.state`, which:
 *   1. survived StrictMode's double-mount (forcing a `navMessageConsumedRef`
 *      guard in ChatPage)
 *   2. survived `history.replaceState({})` because React's location closure
 *      had already snapshotted the original state
 *   3. could re-fire if the user navigated back/forward
 *
 * A take-once store sidesteps all three: the value lives in module memory,
 * the consumer reads it imperatively, and it self-clears after the first
 * sessionId match.
 */
export const usePendingMessage = create<PendingMessageStore>((set, get) => ({
  pending: null,
  set: (pending) => set({ pending }),
  take: (sessionId) => {
    const cur = get().pending
    if (!cur || cur.sessionId !== sessionId) return null
    set({ pending: null })
    return cur
  },
  clear: () => set({ pending: null }),
}))
