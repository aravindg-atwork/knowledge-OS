import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { forgotPassword } from './api/authApi'

export function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [sent, setSent] = useState(false)

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setLoading(true)
    try {
      await forgotPassword(email)
    } finally {
      // This request is always accepted, regardless of whether the address
      // exists, so the UI never branches on the result.
      setLoading(false)
      setSent(true)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4">
      <Card className="w-full max-w-sm p-6">
        <h1 className="mb-1 text-lg font-semibold">Reset your password</h1>
        <p className="mb-6 text-sm text-muted-foreground">
          Enter your email and we'll send you a link to reset your password.
        </p>
        {sent ? (
          <p className="text-sm text-muted-foreground">
            If an account exists for that address, we've sent a reset link.
          </p>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-3">
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="Email"
              autoComplete="username"
              required
            />
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? 'Sending...' : 'Send reset link'}
            </Button>
          </form>
        )}
        <p className="mt-4 text-center text-sm text-muted-foreground">
          <Link to="/login" className="underline">
            Back to sign in
          </Link>
        </p>
      </Card>
    </div>
  )
}
