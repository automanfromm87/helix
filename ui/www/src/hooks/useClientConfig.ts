import { useEffect, useState } from 'react'

import { getCachedClientConfig, type ClientConfigResponse } from '@/api/config'

interface State {
  config: ClientConfigResponse | null
  /** Undefined while the first fetch is in flight; null after a failure. */
  authProvider: string | null | undefined
  loading: boolean
}

/**
 * Single subscription point for the global runtime config (auth provider,
 * github button toggle, etc.). Replaces the duplicated useEffect+useState
 * dance in RequireAuth, LoginGate, HomePage, and friends. The underlying
 * fetch is deduped by getCachedClientConfig's in-flight promise — every
 * consumer of this hook ends up sharing one network request.
 */
export function useClientConfig(): State {
  const [state, setState] = useState<State>({
    config: null,
    authProvider: undefined,
    loading: true,
  })

  useEffect(() => {
    let cancelled = false
    void getCachedClientConfig().then((cfg) => {
      if (cancelled) return
      setState({
        config: cfg,
        authProvider: cfg?.auth_provider ?? null,
        loading: false,
      })
    })
    return () => {
      cancelled = true
    }
  }, [])

  return state
}
