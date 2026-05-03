import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { listProjects } from '@/api/projects'
import { listSessionPlans, type PlanItem } from '@/api/plans'
import {
  getSessionSettings,
  listContextFiles,
  type ContextFileSummary,
  type SessionSettings,
} from '@/api/contextFiles'
import { getSessions } from '@/api/sessions'
import type { ListProjectsResponse, ListSessionResponse } from '@/types/response'

/**
 * Server-state hooks. Each hook exposes a stable key + the cached fetch
 * so multiple components subscribing to the same resource share a single
 * network request, and a mutation can invalidate the matching key to
 * force a refetch instead of every consumer rolling its own loader.
 *
 * Convention: keep the key tuple in `keys.<resource>(...args)` so call
 * sites and `queryClient.invalidateQueries` agree without copy-pasting
 * tuples.
 */
export const queryKeys = {
  projects: ['projects'] as const,
  sessions: ['sessions'] as const,
  sessionPlans: (sessionId: string | undefined) =>
    ['sessions', sessionId, 'plans'] as const,
  contextFiles: (sessionId: string | undefined) =>
    ['sessions', sessionId, 'context-files'] as const,
  sessionSettings: (sessionId: string | undefined) =>
    ['sessions', sessionId, 'settings'] as const,
}

export function useProjectsQuery(): UseQueryResult<ListProjectsResponse> {
  return useQuery({
    queryKey: queryKeys.projects,
    queryFn: listProjects,
  })
}

export function useSessionsQuery(): UseQueryResult<ListSessionResponse> {
  return useQuery({
    queryKey: queryKeys.sessions,
    queryFn: getSessions,
  })
}

export function useSessionPlansQuery(
  sessionId: string | undefined,
): UseQueryResult<PlanItem[]> {
  return useQuery({
    queryKey: queryKeys.sessionPlans(sessionId),
    queryFn: () => listSessionPlans(sessionId as string),
    enabled: Boolean(sessionId),
  })
}

export function useContextFilesQuery(
  sessionId: string | undefined,
): UseQueryResult<ContextFileSummary[]> {
  return useQuery({
    queryKey: queryKeys.contextFiles(sessionId),
    queryFn: () => listContextFiles(sessionId as string),
    enabled: Boolean(sessionId),
  })
}

export function useSessionSettingsQuery(
  sessionId: string | undefined,
): UseQueryResult<SessionSettings | null> {
  return useQuery({
    queryKey: queryKeys.sessionSettings(sessionId),
    queryFn: () =>
      getSessionSettings(sessionId as string).catch(() => null),
    enabled: Boolean(sessionId),
  })
}
