import { apiClient, longOp, type ApiResponse } from './client'

export interface PlanItem {
  plan_id: string
  session_id: string
  title: string
  goal: string
  status: 'planning' | 'executing' | 'completed' | 'failed'
  error?: string | null
  commit_sha?: string | null
  tasks: {
    task_id: string
    plan_id: string
    position: number
    title: string
    details?: string | null
    status: 'pending' | 'running' | 'completed' | 'failed' | 'blocked'
    result?: string | null
    error?: string | null
    retries: number
  }[]
}

export interface MergeResult {
  status: 'merged' | 'resolved' | 'conflict' | 'noop' | 'failed'
  target_session_id: string
  source_session_id: string
  commit_sha: string | null
  resolved_files: string[]
  unresolved_files: string[]
  error: string | null
  plan_id: string | null
}

export interface ForkManySession {
  session_id: string
  project_id: string
  label: string | null
}

/**
 * List all plans for a session, newest first. PlanPanel uses this to
 * navigate prior plans (each follow-up turn produces a new plan row).
 */
export async function listSessionPlans(sessionId: string): Promise<PlanItem[]> {
  const response = await apiClient.get<ApiResponse<{ plans: PlanItem[] }>>(
    `/sessions/${sessionId}/plans`,
  )
  return response.data.data.plans ?? []
}

export async function getPlanDiff(planId: string): Promise<{
  plan_id: string
  commit_sha: string | null
  diff: string
}> {
  const response = await apiClient.get<
    ApiResponse<{ plan_id: string; commit_sha: string | null; diff: string }>
  >(`/plans/${planId}/diff`)
  return response.data.data
}

export async function restorePlan(planId: string): Promise<boolean> {
  const response = await apiClient.post<
    ApiResponse<{ plan_id: string; restored: boolean }>
  >(`/plans/${planId}/restore`)
  return response.data.data?.restored ?? false
}

export async function forkPlan(planId: string): Promise<string> {
  // Long-op timeout: fork copies the project tree (`shutil.copytree`,
  // excluding node_modules but still many files) and on a busy host with
  // several concurrent sandbox lifecycle ops in flight the response can
  // take 1-2 minutes. The default 30s would surface as a spurious "Network
  // error" toast even though the server completes the fork — leaving the
  // user with an orphan session they didn't know was created.
  const response = await apiClient.post<
    ApiResponse<{ plan_id: string; new_session_id: string }>
  >(`/plans/${planId}/fork`, undefined, longOp())
  return response.data.data.new_session_id
}

export async function forkPlanMany(
  planId: string,
  count: number,
  labels?: string[],
): Promise<ForkManySession[]> {
  const r = await apiClient.post<
    ApiResponse<{ plan_id: string; sessions: ForkManySession[] }>
  >(`/plans/${planId}/fork-many`, { count, labels: labels ?? null }, longOp())
  return r.data.data.sessions
}

export async function mergeSessions(
  sessionA: string,
  sessionB: string,
): Promise<MergeResult> {
  const response = await apiClient.post<ApiResponse<MergeResult>>(
    `/sessions/${sessionA}/merge-with/${sessionB}`,
  )
  return response.data.data
}
