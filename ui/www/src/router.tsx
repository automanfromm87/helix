import { type ReactNode } from 'react'
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
import ErrorBoundary from '@/components/ErrorBoundary'
import { getStoredToken } from '@/api/auth'
import { useClientConfig } from '@/hooks/useClientConfig'

const wrap = (scope: string, node: ReactNode): ReactNode => (
  <ErrorBoundary scope={scope}>{node}</ErrorBoundary>
)

function RequireAuth({ children }: { children: ReactNode }) {
  const location = useLocation()
  const { authProvider } = useClientConfig()

  if (authProvider === undefined) return null
  if (authProvider === 'none' || authProvider === null) return <>{children}</>
  if (!getStoredToken()) {
    return <Navigate to={`/login?redirect=${encodeURIComponent(location.pathname)}`} replace />
  }
  return <>{children}</>
}

function LoginGate({ children }: { children: ReactNode }) {
  const { authProvider } = useClientConfig()

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
        <Route index element={wrap('home', <HomePage />)} />
      </Route>
      <Route
        path="/chat"
        element={
          <RequireAuth>
            <MainLayout />
          </RequireAuth>
        }
      >
        <Route index element={wrap('home', <HomePage />)} />
        <Route path=":sessionId" element={wrap('chat', <ChatPage />)} />
      </Route>
      <Route
        path="/home"
        element={
          <RequireAuth>
            <MainLayout />
          </RequireAuth>
        }
      >
        <Route index element={wrap('home', <HomePage />)} />
      </Route>

      <Route path="/share" element={<ShareLayout />}>
        <Route path=":sessionId" element={wrap('share', <SharePage />)} />
      </Route>

      <Route
        path="/compare"
        element={
          <RequireAuth>{wrap('compare', <ComparePage />)}</RequireAuth>
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
