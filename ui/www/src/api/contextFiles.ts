import { apiClient, type ApiResponse } from './client'

export interface ContextFileSummary {
  id: string
  filename: string
  size: number
  created_at: string
}

export interface SessionSettings {
  retrieval_only_context: boolean
}

export async function listContextFiles(sessionId: string): Promise<ContextFileSummary[]> {
  const r = await apiClient.get<ApiResponse<{ files: ContextFileSummary[] }>>(
    `/sessions/${sessionId}/context-files`,
  )
  return r.data.data.files
}

export async function uploadContextFile(
  sessionId: string,
  filename: string,
  content: string,
): Promise<ContextFileSummary> {
  const r = await apiClient.post<ApiResponse<ContextFileSummary>>(
    `/sessions/${sessionId}/context-files`,
    { filename, content },
  )
  return r.data.data
}

export async function deleteContextFile(
  sessionId: string,
  fileId: string,
): Promise<void> {
  await apiClient.delete<ApiResponse<null>>(
    `/sessions/${sessionId}/context-files/${fileId}`,
  )
}

export async function uploadContextFileFromUrl(
  sessionId: string,
  url: string,
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

export async function getSessionSettings(
  sessionId: string,
): Promise<SessionSettings> {
  const r = await apiClient.get<ApiResponse<SessionSettings>>(
    `/sessions/${sessionId}/settings`,
  )
  return r.data.data
}

export async function setRetrievalMode(
  sessionId: string,
  enabled: boolean,
): Promise<void> {
  await apiClient.post<ApiResponse<null>>(
    `/sessions/${sessionId}/retrieval-mode`,
    { enabled },
  )
}
