import { useEffect, useRef, useState } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { ApiError } from '@/lib/apiClient'
import { useAuth } from '@/app/AuthContext'
import { resendVerification, verifyEmail } from './api/authApi'

type VerifyState = 'verifying' | 'error'

export function VerifyEmailPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')
  const { me, loading, refresh } = useAuth()

  if (token) {
    return <TokenVerification token={token} />
  }

  if (loading) {
    return <CenteredCard>Loading…</CenteredCard>
  }

  if (!me) {
    return <Navigate to="/login" replace />
  }

  return <CheckYourEmail email={me.email} refresh={refresh} />
}

function CenteredCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4">
      <Card className="w-full max-w-sm p-6 text-sm text-muted-foreground">{children}</Card>
    </div>
  )
}

function TokenVerification({ token }: { token: string }) {
  const [state, setState] = useState<VerifyState>('verifying')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const navigate = useNavigate()
  const { me, refresh } = useAuth()
  const ran = useRef(false)

  useEffect(() => {
    if (ran.current) return
    ran.current = true
    async function run() {
      try {
        await verifyEmail(token)
        await refresh()
        navigate('/chat')
      } catch (err) {
        if (err instanceof ApiError) {
          setErrorMessage(
            err.code === 'token_expired'
              ? 'That verification link has expired.'
              : 'That verification link is invalid or has already been used.',
          )
        } else {
          setErrorMessage('Unable to verify your email.')
        }
        setState('error')
      }
    }
    void run()
  }, [token, navigate, refresh])

  if (state === 'verifying') {
    return <CenteredCard>Verifying your email…</CenteredCard>
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4">
      <Card className="w-full max-w-sm p-6">
        <h1 className="mb-1 text-lg font-semibold">Verification failed</h1>
        <p className="mb-4 text-sm text-red-500">{errorMessage}</p>
        {me?.email ? <ResendForm email={me.email} /> : <RequestNewLinkForm />}
      </Card>
    </div>
  )
}

function ResendForm({ email }: { email: string }) {
  const [sent, setSent] = useState(false)
  const [loading, setLoading] = useState(false)

  async function handleResend() {
    setLoading(true)
    try {
      await resendVerification(email)
    } finally {
      setLoading(false)
      setSent(true)
    }
  }

  if (sent) {
    return (
      <p className="text-sm text-muted-foreground">
        If that address needs verifying, we've sent a new link to {email}.
      </p>
    )
  }

  return (
    <Button onClick={() => void handleResend()} disabled={loading} className="w-full">
      {loading ? 'Sending...' : 'Send a new verification link'}
    </Button>
  )
}

function RequestNewLinkForm() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setLoading(true)
    try {
      await resendVerification(email)
    } finally {
      setLoading(false)
      setSent(true)
    }
  }

  if (sent) {
    return (
      <p className="text-sm text-muted-foreground">
        If an account exists for that address, we've sent a new verification link.
      </p>
    )
  }

  return (
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
        {loading ? 'Sending...' : 'Send a new verification link'}
      </Button>
    </form>
  )
}

function CheckYourEmail({
  email,
  refresh,
}: {
  email: string
  refresh: () => Promise<void>
}) {
  const [sent, setSent] = useState(false)
  const [loading, setLoading] = useState(false)

  async function handleResend() {
    setLoading(true)
    try {
      await resendVerification(email)
    } finally {
      setLoading(false)
      setSent(true)
    }
  }

  async function handleRefresh() {
    await refresh()
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4">
      <Card className="w-full max-w-sm p-6">
        <h1 className="mb-1 text-lg font-semibold">Check your email</h1>
        <p className="mb-4 text-sm text-muted-foreground">
          We sent a verification link to <span className="font-medium text-foreground">{email}</span>.
          Click the link to verify your account.
        </p>
        {sent ? (
          <p className="text-sm text-muted-foreground">
            If that address needs verifying, we've sent another link.
          </p>
        ) : (
          <Button onClick={() => void handleResend()} disabled={loading} className="w-full">
            {loading ? 'Sending...' : 'Resend verification email'}
          </Button>
        )}
        <button
          onClick={() => void handleRefresh()}
          className="mt-3 w-full text-center text-sm text-muted-foreground underline"
        >
          I've verified, refresh my status
        </button>
      </Card>
    </div>
  )
}
