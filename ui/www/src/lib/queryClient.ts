import { QueryClient } from '@tanstack/react-query'

/**
 * Process-wide TanStack Query client. Defaults tuned for a session-driven
 * agent app:
 *   - staleTime 30s — most lists (sessions, plans, files) tolerate this
 *     without feeling stale, and it kills the "every component remount
 *     refetches" problem the old useEffect+useState code had.
 *   - retry once for transient blips, then surface the error so toasts
 *     fire instead of an indefinite retry storm.
 *   - refetchOnWindowFocus stays on; tab-switch is a strong signal the
 *     user came back and wants fresh data.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
})
