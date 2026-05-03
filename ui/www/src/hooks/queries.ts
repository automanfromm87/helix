import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { listProjects } from '@/api/projects'
import type { ListProjectsResponse } from '@/types/response'

/**
 * Server-state hooks. Each hook exposes a stable key + the cached fetch
 * so multiple components subscribing to the same resource share a single
 * network request, and a mutation can invalidate the matching key to
 * force a refetch instead of every consumer rolling its own loader.
 *
 * Convention: keep the key tuple in `queryKeys.<resource>(...args)` so
 * call sites and `queryClient.invalidateQueries` agree without copy-
 * pasting tuples. Add new resources here as components migrate off the
 * useEffect+useState pattern.
 */
export const queryKeys = {
  projects: ['projects'] as const,
}

export function useProjectsQuery(): UseQueryResult<ListProjectsResponse> {
  return useQuery({
    queryKey: queryKeys.projects,
    queryFn: listProjects,
  })
}
