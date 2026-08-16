import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { ApiError } from '@/lib/apiClient'
import { useAuth } from '@/app/AuthContext'
import { login } from './api/authApi'

export function LoginPage() {
  const [email, setEmail] = useState('demo@acme-corp.com')
  const [password, setPassword] = useState('password123')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const { login: setSession } = useAuth()
  const passwordReset = Boolean((location.state as { passwordReset?: boolean } | null)?.passwordReset)

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const { access_token } = await login(email, password)
      await setSession(access_token)
      navigate('/chat')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Unable to sign in')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4">
      <Card className="w-full max-w-sm p-6">
        <h1 className="mb-1 text-lg font-semibold">Enterprise Knowledge Hub</h1>
        <p className="mb-6 text-sm text-muted-foreground">Sign in to search company knowledge.</p>
        {passwordReset && (
          <p className="mb-3 text-sm text-emerald-600">
            Your password has been reset. Sign in with your new password.
          </p>
        )}
        <form onSubmit={handleSubmit} className="space-y-3">
          <Input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Email"
            autoComplete="username"
          />
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            autoComplete="current-password"
          />
          {error && <p className="text-sm text-red-500">{error}</p>}
          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? 'Signing in...' : 'Sign in'}
          </Button>
        </form>
        <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
          <Link to="/signup" className="underline">
            Create an account
          </Link>
          <Link to="/forgot-password" className="underline">
            Forgot your password?
          </Link>
        </div>
      </Card>
    </div>
  )
}
