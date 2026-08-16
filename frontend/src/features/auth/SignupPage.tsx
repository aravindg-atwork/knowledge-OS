import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { ApiError } from '@/lib/apiClient'
import { useAuth } from '@/app/AuthContext'
import { signup } from './api/authApi'

export function SignupPage() {
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [workspaceName, setWorkspaceName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [workspaceError, setWorkspaceError] = useState<string | null>(null)
  const [emailTaken, setEmailTaken] = useState(false)
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const { login: setSession } = useAuth()

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setWorkspaceError(null)
    setEmailTaken(false)
    setLoading(true)
    try {
      const { access_token } = await signup({
        email,
        password,
        full_name: fullName || undefined,
        workspace_name: workspaceName,
      })
      await setSession(access_token)
      navigate('/verify-email')
    } catch (err) {
      if (err instanceof ApiError && err.code === 'email_taken') {
        setEmailTaken(true)
      } else if (err instanceof ApiError && err.code === 'invalid_workspace_name') {
        setWorkspaceError(err.message)
      } else {
        setError(err instanceof ApiError ? err.message : 'Unable to create account')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4">
      <Card className="w-full max-w-sm p-6">
        <h1 className="mb-1 text-lg font-semibold">Enterprise Knowledge Hub</h1>
        <p className="mb-6 text-sm text-muted-foreground">Create an account to get started.</p>
        <form onSubmit={handleSubmit} className="space-y-3">
          <Input
            type="text"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            placeholder="Full name"
            autoComplete="name"
          />
          <Input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Email"
            autoComplete="username"
            required
          />
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            autoComplete="new-password"
            required
          />
          <div>
            <Input
              type="text"
              value={workspaceName}
              onChange={(e) => setWorkspaceName(e.target.value)}
              placeholder="Workspace name"
              autoComplete="organization"
              required
            />
            {workspaceError && <p className="mt-1 text-sm text-red-500">{workspaceError}</p>}
          </div>
          {emailTaken && (
            <p className="text-sm text-red-500">
              An account with that email already exists.{' '}
              <Link to="/login" className="underline">
                Sign in instead
              </Link>
            </p>
          )}
          {error && <p className="text-sm text-red-500">{error}</p>}
          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? 'Creating account...' : 'Create account'}
          </Button>
        </form>
        <p className="mt-4 text-center text-sm text-muted-foreground">
          Already have an account?{' '}
          <Link to="/login" className="underline">
            Sign in
          </Link>
        </p>
      </Card>
    </div>
  )
}
