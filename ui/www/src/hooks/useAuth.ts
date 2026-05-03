import { useEffect } from 'react'
import { create } from 'zustand'

import {
  clearAuthToken,
  clearStoredTokens,
  getCurrentUser,
  getStoredToken,
  login as apiLogin,
  logout as apiLogout,
  register as apiRegister,
  setAuthToken,
  storeRefreshToken,
  storeToken,
  type LoginRequest,
  type LoginResponse,
  type RegisterRequest,
  type RegisterResponse,
  type User,
} from '@/api/auth'
import { getCachedAuthProvider } from '@/api/config'

interface AuthStore {
  currentUser: User | null
  isAuthenticated: boolean
  isLoading: boolean
  authError: string | null
  initialized: boolean

  initAuth: () => Promise<void>
  loadCurrentUser: () => Promise<void>
  login: (credentials: LoginRequest) => Promise<LoginResponse>
  register: (data: RegisterRequest) => Promise<RegisterResponse>
  logout: (silent?: boolean) => Promise<void>
  clearAuth: () => void
  hasRole: (role: string) => boolean
  clearError: () => void
}

/** Best-effort message extractor for axios / ApiError / Error / unknown. */
function errorMessage(err: unknown): string | undefined {
  if (!err) return undefined
  if (err instanceof Error) return err.message
  if (typeof err === 'object' && 'message' in err) {
    const m = (err as { message?: unknown }).message
    if (typeof m === 'string') return m
  }
  return undefined
}

const ANON_USER: User = {
  id: 'anonymous',
  fullname: 'Anonymous User',
  email: 'anonymous@localhost',
  role: 'user',
  is_active: true,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
}

export const useAuthStore = create<AuthStore>((set, get) => ({
  currentUser: null,
  isAuthenticated: false,
  isLoading: false,
  authError: null,
  initialized: false,

  initAuth: async () => {
    if (get().initialized) return
    set({ initialized: true })
    const authProvider = await getCachedAuthProvider()
    if (authProvider === 'none') {
      set({ currentUser: ANON_USER, isAuthenticated: true })
      return
    }
    const token = getStoredToken()
    if (token) {
      setAuthToken(token)
      await get().loadCurrentUser()
    }
  },

  loadCurrentUser: async () => {
    try {
      set({ isLoading: true, authError: null })
      const user = await getCurrentUser()
      set({ currentUser: user, isAuthenticated: true })
    } catch (error) {
      get().clearAuth()
      set({ authError: errorMessage(error) || 'Failed to load user information' })
    } finally {
      set({ isLoading: false })
    }
  },

  login: async (credentials) => {
    try {
      set({ isLoading: true, authError: null })
      const response = await apiLogin(credentials)
      storeToken(response.access_token)
      storeRefreshToken(response.refresh_token)
      setAuthToken(response.access_token)
      set({ currentUser: response.user, isAuthenticated: true })
      return response
    } catch (error) {
      set({ authError: errorMessage(error) || 'Login failed' })
      throw error
    } finally {
      set({ isLoading: false })
    }
  },

  register: async (data) => {
    try {
      set({ isLoading: true, authError: null })
      const response = await apiRegister(data)
      storeToken(response.access_token)
      storeRefreshToken(response.refresh_token)
      setAuthToken(response.access_token)
      set({ currentUser: response.user, isAuthenticated: true })
      return response
    } catch (error) {
      set({ authError: errorMessage(error) || 'Registration failed' })
      throw error
    } finally {
      set({ isLoading: false })
    }
  },

  logout: async (silent = false) => {
    try {
      if (!silent) {
        set({ isLoading: true, authError: null })
        await apiLogout()
      }
    } catch (e) {
      console.error('Logout API failed:', e)
    } finally {
      get().clearAuth()
      set({ isLoading: false })
    }
  },

  clearAuth: () => {
    clearAuthToken()
    clearStoredTokens()
    set({ currentUser: null, isAuthenticated: false, authError: null })
  },

  hasRole: (role) => get().currentUser?.role === role,

  clearError: () => set({ authError: null }),
}))

/** Hook variant — also wires up the global `auth:logout` event the first time it's used. */
export function useAuth() {
  const store = useAuthStore()

  useEffect(() => {
    const handler = () => useAuthStore.getState().logout(true)
    window.addEventListener('auth:logout', handler)
    return () => window.removeEventListener('auth:logout', handler)
  }, [])

  useEffect(() => {
    if (!useAuthStore.getState().initialized) {
      void useAuthStore.getState().initAuth()
    }
  }, [])

  return store
}
