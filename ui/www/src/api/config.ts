import { apiClient, type ApiResponse } from './client'

export interface ClientConfigResponse {
  auth_provider: string
  show_github_button: boolean
  github_repository_url: string
  google_analytics_id: string | null
}

let clientConfigPromise: Promise<ClientConfigResponse | null> | null = null

export async function getClientConfig(): Promise<ClientConfigResponse> {
  const response = await apiClient.get<ApiResponse<ClientConfigResponse>>('/config/frontend')
  return response.data.data
}

/**
 * Process-wide single-flight cache. Two near-simultaneous callers (router
 * gate, page-level hook, etc.) share the same in-flight promise instead
 * of each issuing their own GET /config/frontend.
 */
export function getCachedClientConfig(): Promise<ClientConfigResponse | null> {
  if (!clientConfigPromise) {
    clientConfigPromise = getClientConfig().catch((error) => {
      console.warn('Failed to load client runtime configuration:', error)
      return null
    })
  }
  return clientConfigPromise
}

export async function getCachedAuthProvider(): Promise<string | null> {
  const cfg = await getCachedClientConfig()
  return cfg?.auth_provider || null
}
