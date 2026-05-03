import { apiClient, type ApiResponse } from './client'
import type { FileViewResponse } from '@/types/response'
import type { FileInfo } from './file'

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

export async function viewFile(sessionId: string, file: string): Promise<FileViewResponse> {
  const response = await apiClient.post<ApiResponse<FileViewResponse>>(
    `/sessions/${sessionId}/file`,
    { file },
  )
  return response.data.data
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
