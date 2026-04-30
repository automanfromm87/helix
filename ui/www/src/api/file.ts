import { apiClient, API_CONFIG, type ApiResponse } from './client'
import type { SignedUrlResponse } from '@/types/response'

export interface FileInfo {
  file_id: string
  filename: string
  content_type?: string
  size?: number
  upload_date: string
  metadata?: Record<string, any>
  file_url?: string
}

export async function uploadFile(
  file: File,
  metadata?: Record<string, any>,
): Promise<FileInfo> {
  const formData = new FormData()
  formData.append('file', file)
  if (metadata) formData.append('metadata', JSON.stringify(metadata))

  const response = await apiClient.post<ApiResponse<FileInfo>>('/files', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return response.data.data
}

export async function downloadFile(fileId: string): Promise<Blob> {
  const response = await apiClient.get(`/files/${fileId}/download`, { responseType: 'blob' })
  return response.data
}

export async function deleteFile(fileId: string): Promise<boolean> {
  try {
    await apiClient.delete<ApiResponse<void>>(`/files/${fileId}`)
    return true
  } catch (error) {
    console.error('Failed to delete file:', error)
    return false
  }
}

export async function getFileInfo(fileId: string): Promise<FileInfo | null> {
  try {
    const response = await apiClient.get<ApiResponse<FileInfo>>(`/files/${fileId}`)
    return response.data.data
  } catch (error) {
    console.error('Failed to get file info:', error)
    return null
  }
}

export async function createFileSignedUrl(
  fileId: string,
  expireMinutes: number = 15,
): Promise<SignedUrlResponse> {
  const response = await apiClient.post<ApiResponse<SignedUrlResponse>>(
    `/files/${fileId}/signed-url`,
    { expire_minutes: expireMinutes },
  )
  return response.data.data
}

export async function getFileDownloadUrl(fileInfo: FileInfo): Promise<string> {
  if (fileInfo.file_url) {
    return `${API_CONFIG.host}${fileInfo.file_url}`
  }
  const signed = await createFileSignedUrl(fileInfo.file_id)
  return `${API_CONFIG.host}${signed.signed_url}`
}
