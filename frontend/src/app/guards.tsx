import { Navigate } from 'react-router-dom'
import { useAuth } from './AuthContext'

function AuthLoading() {
  return <div className="p-8 text-sm text-muted-foreground">Loading…</div>
}

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { me, loading } = useAuth()
  if (loading) return <AuthLoading />
  if (!me) return <Navigate to="/login" replace />
  return <>{children}</>
}

export function RequireVerified({ children }: { children: React.ReactNode }) {
  const { me, loading } = useAuth()
  if (loading) return <AuthLoading />
  if (!me) return <Navigate to="/login" replace />
  if (!me.email_verified) return <Navigate to="/verify-email" replace />
  return <>{children}</>
}

export function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { me, loading } = useAuth()
  if (loading) return <AuthLoading />
  if (!me) return <Navigate to="/login" replace />
  if (me.role !== 'admin') return <Navigate to="/chat" replace />
  return <>{children}</>
}
