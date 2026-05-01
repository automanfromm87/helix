import {
  apiClient,
  API_CONFIG,
  createSSEConnection,
  type ApiResponse,
  type SSECallbacks,
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

export async function getSessionsSSE(
  callbacks?: SSECallbacks<ListSessionResponse>,
): Promise<() => void> {
  return createSSEConnection<ListSessionResponse>('/sessions', { method: 'POST' }, callbacks)
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

export const chatWithSession = async (
  sessionId: string,
  message: string = '',
  eventId?: string,
  attachments?: { file_id: string; filename: string; content_type?: string; size?: number }[],
  callbacks?: SSECallbacks<AgentSSEEvent['data']>,
): Promise<() => void> => {
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
