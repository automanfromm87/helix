import { apiClient, API_CONFIG, type ApiResponse } from './client'
import type { SignedUrlResponse } from '@/types/response'

/**
 * Sandbox-side endpoints: signed URLs for the VNC websocket forward and
 * the interactive pty stream, plus shell session viewers.
 */

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

/**
 * Build a ws(s) URL for the sandbox interactive pty stream.
 *
 * Geometry (cols/rows) and cwd are NOT included as query params here:
 * the signed URL's signature covers the path + signature/expires params
 * verbatim, and tacking extra query params on the end would make
 * signature verification fail. Send geometry over the WS as a
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

