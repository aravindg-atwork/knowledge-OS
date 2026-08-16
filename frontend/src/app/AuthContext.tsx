import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { apiClient, clearStoredToken, getStoredToken, setStoredToken } from '@/lib/apiClient'

export interface WorkspaceSummary {
  id: string
  name: string
  slug: string
  role: 'admin' | 'member'
}

export interface Me {
  user_id: string
  email: string
  full_name: string | null
  email_verified: boolean
  active_workspace_id: string
  role: 'admin' | 'member'
  workspaces: WorkspaceSummary[]
}

interface SwitchWorkspaceResponse {
  access_token: string
  token_type: string
}

interface AuthValue {
  me: Me | null
  loading: boolean
  refresh: () => Promise<void>
  login: (token: string) => Promise<void>
  logout: () => void
  switchWorkspace: (workspaceId: string) => Promise<void>
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    if (!getStoredToken()) {
      setMe(null)
      setLoading(false)
      return
    }
    try {
      setMe(await apiClient.get<Me>('/auth/me'))
    } catch {
      // Any failure to load the current session (expired token, revoked
      // access, network error) is treated as logged-out rather than left
      // in an ambiguous state.
      clearStoredToken()
      setMe(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const login = useCallback(
    async (token: string) => {
      setStoredToken(token)
      setLoading(true)
      await refresh()
    },
    [refresh],
  )

  const logout = useCallback(() => {
    clearStoredToken()
    setMe(null)
  }, [])

  const switchWorkspace = useCallback(
    async (workspaceId: string) => {
      const { access_token } = await apiClient.post<SwitchWorkspaceResponse>(
        '/auth/switch-workspace',
        { workspace_id: workspaceId },
      )
      // The caller's role can differ between workspaces, so we re-fetch
      // /auth/me under the new token rather than assuming anything carries
      // over from the previous session.
      await login(access_token)
    },
    [login],
  )

  return (
    <AuthContext.Provider value={{ me, loading, refresh, login, logout, switchWorkspace }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthProvider')
  return value
}
