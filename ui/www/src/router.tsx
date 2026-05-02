import { useEffect, useState, type ReactNode } from 'react'
import {
  Navigate,
  Outlet,
  Route,
  createBrowserRouter,
  createRoutesFromElements,
  useLocation,
} from 'react-router-dom'

import LoginPage from '@/pages/LoginPage'
import HomePage from '@/pages/HomePage'
import ChatPage from '@/pages/ChatPage'
import ComparePage from '@/pages/ComparePage'
import MainLayout from '@/pages/MainLayout'
import ShareLayout from '@/pages/ShareLayout'
import SharePage from '@/pages/SharePage'
import { getStoredToken } from '@/api/auth'
import { getCachedClientConfig } from '@/api/config'

function RequireAuth({ children }: { children: ReactNode }) {
  const location = useLocation()
  const [authProvider, setAuthProvider] = useState<string | null | undefined>(undefined)

  useEffect(() => {
    let cancelled = false
    void getCachedClientConfig().then((cfg) => {
      if (!cancelled) setAuthProvider(cfg?.auth_provider ?? null)
    })
    return () => {
      cancelled = true
    }
  }, [])

  if (authProvider === undefined) return null

  if (authProvider === 'none' || authProvider === null) return <>{children}</>

  const hasToken = !!getStoredToken()
  if (!hasToken) {
    return <Navigate to={`/login?redirect=${encodeURIComponent(location.pathname)}`} replace />
  }
  return <>{children}</>
}

function LoginGate({ children }: { children: ReactNode }) {
  const [authProvider, setAuthProvider] = useState<string | null | undefined>(undefined)

  useEffect(() => {
    let cancelled = false
    void getCachedClientConfig().then((cfg) => {
      if (!cancelled) setAuthProvider(cfg?.auth_provider ?? null)
    })
    return () => {
      cancelled = true
    }
  }, [])

  if (authProvider === undefined) return null
  if (authProvider === 'none') return <Navigate to="/" replace />
  if (getStoredToken()) return <Navigate to="/" replace />
  return <>{children}</>
}

export const router = createBrowserRouter(
  createRoutesFromElements(
    <Route element={<Outlet />}>
      <Route
        path="/"
        element={
          <RequireAuth>
            <MainLayout />
          </RequireAuth>
        }
      >
        <Route index element={<HomePage />} />
      </Route>
      <Route
        path="/chat"
        element={
          <RequireAuth>
            <MainLayout />
          </RequireAuth>
        }
      >
        <Route index element={<HomePage />} />
        <Route path=":sessionId" element={<ChatPage />} />
      </Route>
      <Route
        path="/home"
        element={
          <RequireAuth>
            <MainLayout />
          </RequireAuth>
        }
      >
        <Route index element={<HomePage />} />
      </Route>

      <Route path="/share" element={<ShareLayout />}>
        <Route path=":sessionId" element={<SharePage />} />
      </Route>

      <Route
        path="/compare"
        element={
          <RequireAuth>
            <ComparePage />
          </RequireAuth>
        }
      />

      <Route
        path="/login"
        element={
          <LoginGate>
            <LoginPage />
          </LoginGate>
        }
      />
    </Route>,
  ),
)
