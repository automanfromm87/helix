import { apiClient, type ApiResponse } from './client'

export interface ClientConfigResponse {
  auth_provider: string
  show_github_button: boolean
  github_repository_url: string
  google_analytics_id: string | null
}

let clientConfigCache: ClientConfigResponse | null = null
let isClientConfigLoaded = false

export async function getClientConfig(): Promise<ClientConfigResponse> {
  const response = await apiClient.get<ApiResponse<ClientConfigResponse>>('/config/frontend')
  return response.data.data
}

export async function getCachedClientConfig(): Promise<ClientConfigResponse | null> {
  if (isClientConfigLoaded) return clientConfigCache
  try {
    clientConfigCache = await getClientConfig()
  } catch (error) {
    console.warn('Failed to load client runtime configuration:', error)
    clientConfigCache = null
  } finally {
    isClientConfigLoaded = true
  }
  return clientConfigCache
}

export async function getCachedAuthProvider(): Promise<string | null> {
  const cfg = await getCachedClientConfig()
  return cfg?.auth_provider || null
}
