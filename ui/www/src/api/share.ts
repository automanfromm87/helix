import { apiClient, type ApiResponse } from './client'
import type { ShareSessionResponse, SharedSessionResponse } from '@/types/response'
import type { FileInfo } from './file'

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
