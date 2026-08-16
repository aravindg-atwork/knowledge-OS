import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { ApiError } from '@/lib/apiClient'
import { resetPassword } from './api/authApi'

export function ResetPasswordPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [expired, setExpired] = useState(false)
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setExpired(false)
    if (!token) {
      setError('This reset link is missing its token.')
      return
    }
    setLoading(true)
    try {
      await resetPassword(token, password)
      navigate('/login', { state: { passwordReset: true } })
    } catch (err) {
      if (err instanceof ApiError && err.code === 'token_expired') {
        setExpired(true)
      } else if (err instanceof ApiError) {
        setError(err.message)
      } else {
        setError('Unable to reset your password')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4">
      <Card className="w-full max-w-sm p-6">
        <h1 className="mb-1 text-lg font-semibold">Choose a new password</h1>
        <p className="mb-6 text-sm text-muted-foreground">
          Enter a new password for your account.
        </p>
        {expired ? (
          <p className="text-sm text-red-500">
            That reset link has expired.{' '}
            <Link to="/forgot-password" className="underline">
              Request a new one
            </Link>
          </p>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-3">
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="New password"
              autoComplete="new-password"
              required
            />
            {error && <p className="text-sm text-red-500">{error}</p>}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? 'Resetting...' : 'Reset password'}
            </Button>
          </form>
        )}
      </Card>
    </div>
  )
}
