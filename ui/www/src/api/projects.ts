import { apiClient, type ApiResponse } from './client'
import type {
  CreateProjectResponse,
  ListProjectsResponse,
} from '@/types/response'

export async function listProjects(): Promise<ListProjectsResponse> {
  const res = await apiClient.get<ApiResponse<ListProjectsResponse>>('/projects')
  return res.data.data
}

export async function createProject(name?: string): Promise<CreateProjectResponse> {
  const res = await apiClient.post<ApiResponse<CreateProjectResponse>>('/projects', {
    name,
  })
  return res.data.data
}

export async function renameProject(projectId: string, name: string): Promise<void> {
  await apiClient.patch<ApiResponse<void>>(`/projects/${projectId}`, { name })
}

export async function updateProjectSystemPrompt(
  projectId: string,
  systemPrompt: string | null,
): Promise<void> {
  await apiClient.patch<ApiResponse<void>>(`/projects/${projectId}`, {
    system_prompt: systemPrompt,
  })
}

export async function deleteProject(projectId: string): Promise<void> {
  await apiClient.delete<ApiResponse<void>>(`/projects/${projectId}`)
}

export async function moveSessionToProject(
  sessionId: string,
  projectId: string | null,
): Promise<void> {
  await apiClient.patch<ApiResponse<void>>(`/sessions/${sessionId}/project`, {
    project_id: projectId,
  })
}
