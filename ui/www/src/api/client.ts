import axios, { AxiosError } from 'axios'
import { fetchEventSource, type EventSourceMessage } from '@microsoft/fetch-event-source'

import {
  clearStoredTokens,
  getStoredRefreshToken,
  getStoredToken,
  storeToken,
} from './auth'

export const API_CONFIG = {
  host: (import.meta as any).env?.VITE_API_URL || '',
  version: 'v1',
  timeout: 30_000,
}

export const BASE_URL = API_CONFIG.host
  ? `${API_CONFIG.host}/api/${API_CONFIG.version}`
  : `/api/${API_CONFIG.version}`

const LOGIN_ROUTE = '/login'

export interface ApiResponse<T> {
  code: number
  msg: string
  data: T
}

export interface ApiError {
  code: number
  message: string
  details?: unknown
}

export const apiClient = axios.create({
  baseURL: BASE_URL,
  timeout: API_CONFIG.timeout,
  headers: { 'Content-Type': 'application/json' },
})

apiClient.interceptors.request.use(
  (config) => {
    const token = getStoredToken()
    if (token && !config.headers.Authorization) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

let isRefreshing = false
let failedQueue: Array<{ resolve: (token: string | null) => void; reject: (err: unknown) => void }> = []

const processQueue = (error: unknown, token: string | null = null) => {
  failedQueue.forEach(({ resolve, reject }) => (error ? reject(error) : resolve(token)))
  failedQueue = []
}

const redirectToLogin = () => {
  if (window.location.pathname === LOGIN_ROUTE) return
  setTimeout(() => {
    window.location.href = LOGIN_ROUTE
  }, 100)
}

const refreshAuthToken = async (): Promise<string | null> => {
  if (isRefreshing) {
    return new Promise((resolve, reject) => {
      failedQueue.push({ resolve, reject })
    })
  }

  isRefreshing = true
  const refreshToken = getStoredRefreshToken()

  if (!refreshToken) {
    clearStoredTokens()
    delete apiClient.defaults.headers.common.Authorization
    window.dispatchEvent(new CustomEvent('auth:logout'))
    redirectToLogin()
    isRefreshing = false
    throw new Error('No refresh token available')
  }

  try {
    const response = await apiClient.post(
      '/auth/refresh',
      { refresh_token: refreshToken },
      { __isRefreshRequest: true } as any,
    )

    if (response.data?.data) {
      const newAccessToken = response.data.data.access_token as string
      storeToken(newAccessToken)
      apiClient.defaults.headers.common.Authorization = `Bearer ${newAccessToken}`
      processQueue(null, newAccessToken)
      return newAccessToken
    }
    throw new Error('Invalid refresh response')
  } catch (refreshError) {
    clearStoredTokens()
    delete apiClient.defaults.headers.common.Authorization
    processQueue(refreshError, null)
    window.dispatchEvent(new CustomEvent('auth:logout'))
    redirectToLogin()
    throw refreshError
  } finally {
    isRefreshing = false
  }
}

apiClient.interceptors.response.use(
  (response) => {
    if (response.data && typeof response.data.code === 'number') {
      if (response.data.code !== 0) {
        const apiError: ApiError = {
          code: response.data.code,
          message: response.data.msg || 'Unknown error',
          details: response.data,
        }
        return Promise.reject(apiError)
      }
    }
    return response
  },
  async (error: AxiosError) => {
    const originalRequest = error.config as any

    if (originalRequest?.__isRefreshRequest) {
      const apiError: ApiError = {
        code: error.response?.status || 500,
        message: 'Token refresh failed',
        details: error.response?.data,
      }
      return Promise.reject(apiError)
    }

    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
      originalRequest._retry = true
      try {
        const newAccessToken = await refreshAuthToken()
        if (newAccessToken) {
          originalRequest.headers.Authorization = `Bearer ${newAccessToken}`
          return apiClient(originalRequest)
        }
      } catch (e) {
        console.error('Token refresh failed:', e)
      }
    }

    const apiError: ApiError = { code: 500, message: 'Request failed' }

    if (error.response) {
      apiError.code = error.response.status
      const data = error.response.data as any
      if (data && typeof data === 'object') {
        if (data.code && data.msg) {
          apiError.code = data.code
          apiError.message = data.msg
        } else {
          apiError.message = data.message || error.response.statusText || 'Request failed'
        }
        apiError.details = data
      } else {
        apiError.message = error.response.statusText || 'Request failed'
      }
    } else if (error.request) {
      apiError.code = 503
      apiError.message = 'Network error, please check your connection'
    }

    console.error('API Error:', apiError)
    return Promise.reject(apiError)
  },
)

export interface SSECallbacks<T = unknown> {
  onOpen?: () => void
  onMessage?: (event: { event: string; data: T }) => void
  onClose?: () => void
  onError?: (error: Error) => void
}

export interface SSEOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  body?: unknown
  headers?: Record<string, string>
}

const handleSSEAuthError = async <T>(
  callbacks: SSECallbacks<T>,
): Promise<boolean> => {
  try {
    const newAccessToken = await refreshAuthToken()
    if (newAccessToken) {
      window.dispatchEvent(new CustomEvent('auth:token-refreshed'))
      return true
    }
    return false
  } catch (refreshError) {
    callbacks.onError?.(refreshError as Error)
    return false
  }
}

/** Open an SSE connection. Returns a function that aborts the stream. */
export const createSSEConnection = async <T = unknown>(
  endpoint: string,
  options: SSEOptions = {},
  callbacks: SSECallbacks<T> = {},
): Promise<() => void> => {
  const { onOpen, onMessage, onClose, onError } = callbacks
  const { method = 'GET', body, headers = {} } = options

  const abortController = new AbortController()
  const apiUrl = `${BASE_URL}${endpoint}`

  const requestHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    ...headers,
  }

  const token = getStoredToken()
  if (token && !requestHeaders.Authorization) {
    requestHeaders.Authorization = `Bearer ${token}`
  }

  const createConnection = async (): Promise<void> => {
    return new Promise((_resolve, reject) => {
      if (abortController.signal.aborted) {
        reject(new Error('Connection aborted'))
        return
      }

      const ssePromise = fetchEventSource(apiUrl, {
        method,
        headers: requestHeaders,
        openWhenHidden: true,
        body: body ? JSON.stringify(body) : undefined,
        signal: abortController.signal,
        async onopen(response) {
          if (response.status === 401) {
            const refreshSuccess = await handleSSEAuthError(callbacks)
            if (refreshSuccess) {
              const newToken = getStoredToken()
              if (newToken) {
                requestHeaders.Authorization = `Bearer ${newToken}`
                setTimeout(() => createConnection().catch(console.error), 1000)
              }
            }
            return
          }
          if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`)
          }
          onOpen?.()
        },
        onmessage(event: EventSourceMessage) {
          if (event.event && event.event.trim() !== '') {
            onMessage?.({
              event: event.event,
              data: JSON.parse(event.data) as T,
            })
          }
        },
        onclose() {
          onClose?.()
        },
        onerror(err: unknown) {
          const error = err instanceof Error ? err : new Error(String(err))
          console.error('EventSource error:', error)
          onError?.(error)
          reject(error)
        },
      })

      ssePromise.catch(reject)
    })
  }

  createConnection().catch((error) => {
    if (!abortController.signal.aborted) {
      console.error('SSE connection failed:', error)
    }
  })

  return () => abortController.abort()
}
