import { apiClient, createSSEConnection, type ApiResponse, type SSECallbacks, type SSEHandle } from './client'
import type { AgentSSEEvent } from '@/types/event'
import type {
  CreateSessionResponse,
  GetSessionResponse,
  ListSessionResponse,
} from '@/types/response'

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

export async function clearUnreadMessageCount(sessionId: string): Promise<void> {
  await apiClient.post<ApiResponse<void>>(`/sessions/${sessionId}/clear_unread_message_count`)
}

export const chatWithSession = (
  sessionId: string,
  message: string = '',
  eventId?: string,
  attachments?: { file_id: string; filename: string; content_type?: string; size?: number }[],
  callbacks?: SSECallbacks<AgentSSEEvent['data']>,
): SSEHandle => {
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
