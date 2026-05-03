import axios, {
  AxiosError,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from 'axios'
import { fetchEventSource, type EventSourceMessage } from '@microsoft/fetch-event-source'

import {
  clearStoredTokens,
  getStoredRefreshToken,
  getStoredToken,
  storeToken,
} from './auth'
import * as bus from '@/lib/eventBus'

// Module-augment axios so we can stop sprinkling `as any` to attach the two
// flags the refresh interceptor needs.
declare module 'axios' {
  export interface AxiosRequestConfig {
    /** Marks the refresh-token request itself, so the interceptor doesn't try to refresh again on its 401. */
    __isRefreshRequest?: boolean
    /** Marks an original request that has already been retried once after a refresh. */
    _retry?: boolean
  }
}

interface ImportMetaEnv {
  VITE_API_URL?: string
}

export const API_CONFIG = {
  host: (import.meta as unknown as { env?: ImportMetaEnv }).env?.VITE_API_URL || '',
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

/**
 * Per-call timeout override for known-long server operations (fork,
 * fork-many, large URL ingestion). Use as the third arg to apiClient
 * verbs instead of inlining `{ timeout: 5 * 60 * 1000 }` everywhere.
 */
export const LONG_OP_TIMEOUT_MS = 5 * 60 * 1000
export const longOp = (overrides?: AxiosRequestConfig): AxiosRequestConfig => ({
  timeout: LONG_OP_TIMEOUT_MS,
  ...overrides,
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
    bus.emit('auth:logout', undefined)
    redirectToLogin()
    isRefreshing = false
    throw new Error('No refresh token available')
  }

  try {
    const response = await apiClient.post(
      '/auth/refresh',
      { refresh_token: refreshToken },
      { __isRefreshRequest: true } satisfies AxiosRequestConfig,
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
    bus.emit('auth:logout', undefined)
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
    const originalRequest = error.config as InternalAxiosRequestConfig | undefined

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
      const data = error.response.data
      if (data && typeof data === 'object') {
        const body = data as { code?: number; msg?: string; message?: string }
        if (typeof body.code === 'number' && body.msg) {
          apiError.code = body.code
          apiError.message = body.msg
        } else {
          apiError.message = body.message || error.response.statusText || 'Request failed'
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
  /**
   * If no event arrives in this many ms while the stream is open, the
   * connection is treated as dead and `onError` fires. sse-starlette keeps
   * sockets alive with periodic comments, so this only trips when the
   * underlying TCP/proxy is genuinely wedged. 0 disables.
   */
  idleTimeoutMs?: number
  /**
   * Whether to keep the connection alive when the tab is hidden. Defaults
   * to true (chat needs it); subscription endpoints can opt out so a pile
   * of background tabs doesn't pin one stream each.
   */
  openWhenHidden?: boolean
}

export interface SSEHandle {
  cancel: () => void
}

/**
 * Sentinel thrown from `onerror` to stop fetch-event-source's default
 * reconnect loop. Without this, an `onerror` that doesn't throw silently
 * triggers a retry, even after the caller has already torn down its
 * UI state — the resurrected stream then pushes events into a half-dead
 * controller.
 */
class SSEFatalError extends Error {}

/** Build the headers used for an SSE request, attaching a fresh token. */
const buildSSEHeaders = (extra: Record<string, string>): Record<string, string> => {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...extra,
  }
  const token = getStoredToken()
  if (token && !headers.Authorization) {
    headers.Authorization = `Bearer ${token}`
  }
  return headers
}

/**
 * Open an SSE connection. Returns synchronously with a `cancel` handle so
 * callers can abort even before `onopen` fires (e.g. user clicks Stop in
 * the small window between `chat()` issuing the request and the server
 * acknowledging it).
 *
 * Lifecycle:
 *   - `onopen`  fires once per successful (re)connection
 *   - `onmessage` fires per parsed event; malformed JSON is logged and
 *      dropped so a single bad chunk can't kill the whole stream
 *   - `onclose` fires when the server cleanly ends the stream
 *   - `onerror` fires for transport / parse / auth-refresh failures and
 *      then the stream is torn down (no auto-reconnect — the caller can
 *      decide whether to retry by opening a new connection).
 */
export const createSSEConnection = <T = unknown>(
  endpoint: string,
  options: SSEOptions = {},
  callbacks: SSECallbacks<T> = {},
): SSEHandle => {
  const { onOpen, onMessage, onClose, onError } = callbacks
  const {
    method = 'GET',
    body,
    headers = {},
    idleTimeoutMs = 90_000,
    openWhenHidden = true,
  } = options

  const abortController = new AbortController()
  const apiUrl = `${BASE_URL}${endpoint}`
  const serializedBody = body !== undefined ? JSON.stringify(body) : undefined

  let closed = false
  let idleTimer: ReturnType<typeof setTimeout> | null = null
  // `auth:retried` guards against a refresh-loop: if a 401 fires immediately
  // after we already refreshed and reconnected, treat it as fatal instead of
  // looping forever.
  let authRetried = false

  const finish = (err?: Error) => {
    if (closed) return
    closed = true
    if (idleTimer) {
      clearTimeout(idleTimer)
      idleTimer = null
    }
    abortController.abort()
    if (err) onError?.(err)
    else onClose?.()
  }

  const armIdle = () => {
    if (!idleTimeoutMs) return
    if (idleTimer) clearTimeout(idleTimer)
    idleTimer = setTimeout(() => {
      finish(new Error(`SSE idle for ${idleTimeoutMs}ms`))
    }, idleTimeoutMs)
  }

  const runOnce = async (requestHeaders: Record<string, string>): Promise<void> => {
    await fetchEventSource(apiUrl, {
      method,
      headers: requestHeaders,
      openWhenHidden,
      body: serializedBody,
      signal: abortController.signal,
      async onopen(response) {
        if (response.status === 401) {
          // Throw to break out of fetch-event-source — the outer driver
          // catches, refreshes the token, and retries with fresh headers.
          throw new SSEFatalError('unauthorized')
        }
        if (!response.ok) {
          throw new SSEFatalError(`HTTP ${response.status}: ${response.statusText}`)
        }
        armIdle()
        onOpen?.()
      },
      onmessage(event: EventSourceMessage) {
        armIdle()
        // SSE spec: when no `event:` field is present, the type defaults to
        // 'message'. Don't drop those — backend servers (or proxies that
        // strip event names) would otherwise go silent.
        const eventName = event.event && event.event.trim() !== '' ? event.event : 'message'
        if (event.data === '') return // pure keep-alive comments come through as empty
        let data: T
        try {
          data = JSON.parse(event.data) as T
        } catch (e) {
          console.error('[SSE] dropped malformed event', { eventName, raw: event.data, e })
          return
        }
        onMessage?.({ event: eventName, data })
      },
      onclose() {
        // Server cleanly ended the stream — propagate as close, not error.
        finish()
      },
      onerror(err: unknown) {
        // Re-throw to terminate fetch-event-source's internal retry loop.
        // The outer try/catch promotes it to onError on the SSE handle.
        throw err instanceof Error ? err : new Error(String(err))
      },
    })
  }

  const drive = async () => {
    let err: unknown
    try {
      await runOnce(buildSSEHeaders(headers))
      finish()
      return
    } catch (e) {
      err = e
    }
    if (closed || abortController.signal.aborted) return

    // 401 → refresh once, then reconnect with fresh headers. Any other
    // error (or a second 401) is terminal.
    if (err instanceof SSEFatalError && err.message === 'unauthorized' && !authRetried) {
      authRetried = true
      try {
        const newToken = await refreshAuthToken()
        if (!newToken) {
          finish(new Error('Token refresh failed'))
          return
        }
        bus.emit('auth:token-refreshed', undefined)
      } catch (refreshErr) {
        finish(refreshErr instanceof Error ? refreshErr : new Error(String(refreshErr)))
        return
      }
      if (closed || abortController.signal.aborted) return
      try {
        await runOnce(buildSSEHeaders(headers))
        finish()
      } catch (retryErr) {
        if (closed || abortController.signal.aborted) return
        finish(retryErr instanceof Error ? retryErr : new Error(String(retryErr)))
      }
      return
    }

    const wrapped = err instanceof Error ? err : new Error(String(err))
    console.error('[SSE] error', wrapped)
    finish(wrapped)
  }

  void drive()

  return {
    cancel: () => finish(),
  }
}
