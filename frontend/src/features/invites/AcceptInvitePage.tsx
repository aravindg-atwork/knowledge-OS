import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { ApiError } from '@/lib/apiClient'
import { useAuth } from '@/app/AuthContext'
import { acceptInvite, previewInvite, type InvitePreview } from './api/invitesApi'

const INVALID_MESSAGE = 'This invitation is no longer valid. Ask your workspace admin to send a new one.'
const EXPIRED_MESSAGE = 'This invitation has expired. Ask your workspace admin to send a new one.'

function CenteredCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4">
      <Card className="w-full max-w-sm p-6 text-sm text-muted-foreground">{children}</Card>
    </div>
  )
}

export function AcceptInvitePage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')
  const { me, login, logout } = useAuth()
  const navigate = useNavigate()

  const [preview, setPreview] = useState<InvitePreview | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [loadingPreview, setLoadingPreview] = useState(true)

  const [fullName, setFullName] = useState('')
  const [password, setPassword] = useState('')
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [alreadyMember, setAlreadyMember] = useState(false)
  const [emailMismatch, setEmailMismatch] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!token) {
      setPreviewError('This invitation link is missing its token.')
      setLoadingPreview(false)
      return
    }
    let cancelled = false
    async function run() {
      try {
        const data = await previewInvite(token as string)
        if (!cancelled) setPreview(data)
      } catch (err) {
        if (cancelled) return
        if (err instanceof ApiError && err.code === 'token_expired') {
          setPreviewError(EXPIRED_MESSAGE)
        } else if (err instanceof ApiError && err.code === 'invalid_token') {
          setPreviewError(INVALID_MESSAGE)
        } else {
          setPreviewError('Unable to load this invitation.')
        }
      } finally {
        if (!cancelled) setLoadingPreview(false)
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [token])

  async function handleAccept(event?: React.FormEvent) {
    event?.preventDefault()
    if (!token) return
    setSubmitError(null)
    setAlreadyMember(false)
    setEmailMismatch(false)
    setSubmitting(true)
    try {
      const { access_token } = await acceptInvite(
        me ? { token } : { token, password, full_name: fullName || undefined },
      )
      await login(access_token)
      navigate('/chat')
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === 'already_member') {
          setAlreadyMember(true)
        } else if (err.code === 'invite_email_mismatch') {
          setEmailMismatch(true)
        } else if (err.code === 'token_expired') {
          setPreviewError(EXPIRED_MESSAGE)
        } else if (err.code === 'invalid_token') {
          setPreviewError(INVALID_MESSAGE)
        } else {
          setSubmitError(err.message)
        }
      } else {
        setSubmitError('Unable to accept this invitation.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  function handleSignOut() {
    logout()
    setEmailMismatch(false)
  }

  if (loadingPreview) {
    return <CenteredCard>Loading invitation…</CenteredCard>
  }

  if (previewError) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4">
        <Card className="w-full max-w-sm p-6">
          <h1 className="mb-1 text-lg font-semibold">Invitation unavailable</h1>
          <p className="text-sm text-red-500">{previewError}</p>
        </Card>
      </div>
    )
  }

  if (!preview) {
    return null
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4">
      <Card className="w-full max-w-sm p-6">
        <h1 className="mb-1 text-lg font-semibold">
          You&apos;ve been invited to join <strong>{preview.workspace_name}</strong>
        </h1>
        <p className="mb-6 text-sm text-muted-foreground">
          Accept the invitation below to join the workspace.
        </p>

        <div className="mb-3">
          <Input type="email" value={preview.email} readOnly disabled />
        </div>

        {alreadyMember ? (
          <p className="text-sm text-muted-foreground">
            You&apos;re already in this workspace.{' '}
            <Link to="/chat" className="underline">
              Go to chat
            </Link>
          </p>
        ) : emailMismatch ? (
          <div className="space-y-3 text-sm text-red-500">
            <p>
              You&apos;re signed in as {me?.email ?? 'a different account'}, which doesn&apos;t match this
              invitation. Sign out to accept it as {preview.email}.
            </p>
            <Button onClick={handleSignOut} variant="outline" className="w-full">
              Sign out
            </Button>
          </div>
        ) : me ? (
          <>
            {submitError && <p className="mb-3 text-sm text-red-500">{submitError}</p>}
            <Button onClick={() => void handleAccept()} disabled={submitting} className="w-full">
              {submitting ? 'Accepting...' : 'Accept invitation'}
            </Button>
          </>
        ) : (
          <form onSubmit={(e) => void handleAccept(e)} className="space-y-3">
            <Input
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Full name"
              autoComplete="name"
            />
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Password"
              autoComplete="new-password"
              required
            />
            {submitError && <p className="text-sm text-red-500">{submitError}</p>}
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? 'Accepting...' : 'Accept invitation'}
            </Button>
          </form>
        )}
      </Card>
    </div>
  )
}
