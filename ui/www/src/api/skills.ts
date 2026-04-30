import { apiClient, type ApiResponse } from './client'
import type { ListSkillsResponse } from '@/types/response'

export async function listSkills(): Promise<ListSkillsResponse> {
  const res = await apiClient.get<ApiResponse<ListSkillsResponse>>('/skills')
  return res.data.data
}
