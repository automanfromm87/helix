import {
  apiClient,
  API_CONFIG,
  createSSEConnection,
  longOp,
  type ApiResponse,
  type SSECallbacks,
  type SSEHandle,
} from './client'
import type { AgentSSEEvent } from '@/types/event'
import type {
  CreateSessionResponse,
  GetSessionResponse,
  ShellViewResponse,
  FileViewResponse,
  ListSessionResponse,
  SignedUrlResponse,
  ShareSessionResponse,
  SharedSessionResponse,
} from '@/types/response'
import type { FileInfo } from './file'

export async function createSession(
  projectId?: string | null,
): Promise<CreateSessionResponse> {
  const response = await apiClient.put<ApiResponse<CreateSessionResponse>>('/sessions', {
    project_id: projectId ?? null,
  })
  return response.data.data
}

export async function getSession(
  sessionId: string,
  options: { eventsLimit?: number; eventsBefore?: string } = {},
): Promise<GetSessionResponse> {
  const params: Record<string, string | number> = {}
  if (options.eventsLimit !== undefined) params.events_limit = options.eventsLimit
  if (options.eventsBefore !== undefined) params.events_before = options.eventsBefore
  const response = await apiClient.get<ApiResponse<GetSessionResponse>>(
    `/sessions/${sessionId}`,
    Object.keys(params).length > 0 ? { params } : undefined,
  )
  return response.data.data
}

export async function getSessions(): Promise<ListSessionResponse> {
  const response = await apiClient.get<ApiResponse<ListSessionResponse>>('/sessions')
  return response.data.data
}

export async function searchSessions(query: string): Promise<ListSessionResponse> {
  const response = await apiClient.get<ApiResponse<ListSessionResponse>>('/sessions/search', {
    params: { q: query },
  })
  return response.data.data
}

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

/**
 * List all plans for a session, newest first. Used by PlanPanel to
 * navigate prior plans (e.g. follow-up turns produce new plan rows;
 * the user wants to see what the prior turn's plan looked like).
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

export async function mergeSessions(
  sessionA: string,
  sessionB: string,
): Promise<MergeResult> {
  const response = await apiClient.post<ApiResponse<MergeResult>>(
    `/sessions/${sessionA}/merge-with/${sessionB}`,
  )
  return response.data.data
}

export async function deleteSession(sessionId: string): Promise<void> {
  await apiClient.delete<ApiResponse<void>>(`/sessions/${sessionId}`)
}

export async function regenerateFromMessage(
  sessionId: string,
  fromEventId: string,
  message: string,
  attachments?: { file_id: string; filename: string; content_type?: string; size?: number }[],
): Promise<void> {
  await apiClient.post<ApiResponse<void>>(`/sessions/${sessionId}/regenerate`, {
    from_event_id: fromEventId,
    message,
    attachments,
  })
}

export async function stopSession(sessionId: string): Promise<void> {
  await apiClient.post<ApiResponse<void>>(`/sessions/${sessionId}/stop`)
}

export async function createVncSignedUrl(
  sessionId: string,
  expireMinutes: number = 15,
): Promise<SignedUrlResponse> {
  const response = await apiClient.post<ApiResponse<SignedUrlResponse>>(
    `/sessions/${sessionId}/vnc/signed-url`,
    { expire_minutes: expireMinutes },
  )
  return response.data.data
}

/** Build a wss URL for the sandbox VNC websocket forward. */
export const getVNCUrl = async (
  sessionId: string,
  expireMinutes: number = 15,
): Promise<string> => {
  const signed = await createVncSignedUrl(sessionId, expireMinutes)
  // When VITE_API_URL is empty (using vite proxy / same-origin), build a
  // ws(s)://-based URL from window.location so the browser can connect.
  const host = API_CONFIG.host || `${window.location.protocol}//${window.location.host}`
  const wsBase = host.replace(/^http/, 'ws')
  return `${wsBase}${signed.signed_url}`
}

export async function createShellStreamSignedUrl(
  sessionId: string,
  expireMinutes: number = 15,
): Promise<SignedUrlResponse> {
  const response = await apiClient.post<ApiResponse<SignedUrlResponse>>(
    `/sessions/${sessionId}/shell/stream/signed-url`,
    { expire_minutes: expireMinutes },
  )
  return response.data.data
}

/** Build a ws(s) URL for the sandbox interactive pty stream.
 *
 * Geometry (cols/rows) and cwd are NOT included as query params here:
 * the signed URL's signature covers the path + signature/expires
 * params verbatim, and tacking extra query params on the end would
 * make signature verification fail. Send geometry over the WS as a
 * `{type:"resize"}` message immediately after the connection opens.
 */
export const getShellStreamUrl = async (
  sessionId: string,
  opts: { expireMinutes?: number } = {},
): Promise<string> => {
  const signed = await createShellStreamSignedUrl(sessionId, opts.expireMinutes ?? 15)
  const host = API_CONFIG.host || `${window.location.protocol}//${window.location.host}`
  const wsBase = host.replace(/^http/, 'ws')
  return `${wsBase}${signed.signed_url}`
}

export const chatWithSession = (
  sessionId: string,
  message: string = '',
  eventId?: string,
  attachments?: { file_id: string; filename: string; content_type?: string; size?: number }[],
  callbacks?: SSECallbacks<AgentSSEEvent['data']>,
): SSEHandle => {
  return createSSEConnection<AgentSSEEvent['data']>(
    `/sessions/${sessionId}/chat`,
    {
      method: 'POST',
      body: {
        message,
        timestamp: Math.floor(Date.now() / 1000),
        event_id: eventId,
        attachments,
      },
    },
    callbacks,
  )
}

export async function viewShellSession(
  sessionId: string,
  shellSessionId: string,
): Promise<ShellViewResponse> {
  const response = await apiClient.post<ApiResponse<ShellViewResponse>>(
    `/sessions/${sessionId}/shell`,
    { session_id: shellSessionId },
  )
  return response.data.data
}

export async function viewFile(sessionId: string, file: string): Promise<FileViewResponse> {
  const response = await apiClient.post<ApiResponse<FileViewResponse>>(
    `/sessions/${sessionId}/file`,
    { file },
  )
  return response.data.data
}

export interface FileListEntry {
  name: string
  path: string
  is_dir: boolean
  size: number
}
export interface FileListResponse {
  path: string
  entries: FileListEntry[]
}

export async function listDir(
  sessionId: string,
  path: string,
  options: { showHidden?: boolean } = {},
): Promise<FileListResponse> {
  const response = await apiClient.post<ApiResponse<FileListResponse>>(
    `/sessions/${sessionId}/file/list`,
    { path, show_hidden: options.showHidden ?? false },
  )
  return response.data.data
}

export async function getSessionFiles(sessionId: string): Promise<FileInfo[]> {
  const response = await apiClient.get<ApiResponse<FileInfo[]>>(`/sessions/${sessionId}/files`)
  return response.data.data
}

export async function clearUnreadMessageCount(sessionId: string): Promise<void> {
  await apiClient.post<ApiResponse<void>>(`/sessions/${sessionId}/clear_unread_message_count`)
}

export async function shareSession(sessionId: string): Promise<ShareSessionResponse> {
  const response = await apiClient.post<ApiResponse<ShareSessionResponse>>(
    `/sessions/${sessionId}/share`,
  )
  return response.data.data
}

export async function unshareSession(sessionId: string): Promise<ShareSessionResponse> {
  const response = await apiClient.delete<ApiResponse<ShareSessionResponse>>(
    `/sessions/${sessionId}/share`,
  )
  return response.data.data
}

export async function getSharedSession(sessionId: string): Promise<SharedSessionResponse> {
  const response = await apiClient.get<ApiResponse<SharedSessionResponse>>(
    `/sessions/shared/${sessionId}`,
  )
  return response.data.data
}

export async function getSharedSessionFiles(sessionId: string): Promise<FileInfo[]> {
  const response = await apiClient.get<ApiResponse<FileInfo[]>>(
    `/sessions/${sessionId}/share/files`,
  )
  return response.data.data
}

export interface ContextFileSummary {
  id: string
  filename: string
  size: number
  created_at: string
}

export async function listContextFiles(sessionId: string): Promise<ContextFileSummary[]> {
  const r = await apiClient.get<ApiResponse<{ files: ContextFileSummary[] }>>(
    `/sessions/${sessionId}/context-files`,
  )
  return r.data.data.files
}

export async function uploadContextFile(
  sessionId: string, filename: string, content: string,
): Promise<ContextFileSummary> {
  const r = await apiClient.post<ApiResponse<ContextFileSummary>>(
    `/sessions/${sessionId}/context-files`,
    { filename, content },
  )
  return r.data.data
}

export async function deleteContextFile(
  sessionId: string, fileId: string,
): Promise<void> {
  await apiClient.delete<ApiResponse<null>>(
    `/sessions/${sessionId}/context-files/${fileId}`,
  )
}

export async function uploadContextFileFromUrl(
  sessionId: string, url: string,
): Promise<ContextFileSummary> {
  // Same as the default 30s, kept explicit because the server fetches the
  // URL synchronously and a slow upstream (huge docs page) is the most
  // likely culprit for timeouts on this endpoint.
  const r = await apiClient.post<ApiResponse<ContextFileSummary>>(
    `/sessions/${sessionId}/context-files/from-url`,
    { url },
    { timeout: 30_000 },
  )
  return r.data.data
}

export interface SessionSettings {
  retrieval_only_context: boolean
}

export async function getSessionSettings(
  sessionId: string,
): Promise<SessionSettings> {
  const r = await apiClient.get<ApiResponse<SessionSettings>>(
    `/sessions/${sessionId}/settings`,
  )
  return r.data.data
}

export async function setRetrievalMode(
  sessionId: string, enabled: boolean,
): Promise<void> {
  await apiClient.post<ApiResponse<null>>(
    `/sessions/${sessionId}/retrieval-mode`,
    { enabled },
  )
}

export interface ForkManySession {
  session_id: string
  project_id: string
  label: string | null
}

export async function forkPlanMany(
  planId: string, count: number, labels?: string[],
): Promise<ForkManySession[]> {
  const r = await apiClient.post<
    ApiResponse<{ plan_id: string; sessions: ForkManySession[] }>
  >(
    `/plans/${planId}/fork-many`,
    { count, labels: labels ?? null },
    longOp(),
  )
  return r.data.data.sessions
}
