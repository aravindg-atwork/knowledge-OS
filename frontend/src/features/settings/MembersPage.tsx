import { useEffect, useState } from 'react'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ApiError } from '@/lib/apiClient'
import { cn } from '@/lib/utils'
import { SettingsNav } from './SettingsNav'
import {
  createInvitation,
  listInvitations,
  listMembers,
  removeMember,
  revokeInvitation,
  updateMemberRole,
  type Invitation,
  type Member,
} from './api/settingsApi'

const selectClass = cn(
  'rounded-md border border-border bg-transparent px-2 py-1.5 text-sm outline-none focus:ring-2 focus:ring-primary/40',
)

export function MembersPage() {
  const [members, setMembers] = useState<Member[]>([])
  const [invitations, setInvitations] = useState<Invitation[]>([])
  const [loading, setLoading] = useState(true)
  const [memberError, setMemberError] = useState<string | null>(null)
  const [memberErrorUserId, setMemberErrorUserId] = useState<string | null>(null)

  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<'admin' | 'member'>('member')
  const [inviteError, setInviteError] = useState<string | null>(null)
  const [inviting, setInviting] = useState(false)

  async function loadAll() {
    const [memberList, invitationList] = await Promise.all([listMembers(), listInvitations()])
    setMembers(memberList)
    setInvitations(invitationList)
  }

  useEffect(() => {
    loadAll().finally(() => setLoading(false))
  }, [])

  async function handleRoleChange(userId: string, role: 'admin' | 'member') {
    setMemberError(null)
    setMemberErrorUserId(null)
    try {
      await updateMemberRole(userId, role)
      await loadAll()
    } catch (err) {
      if (err instanceof ApiError && err.code === 'last_admin') {
        setMemberErrorUserId(userId)
        setMemberError('A workspace must keep at least one admin.')
      } else {
        setMemberErrorUserId(userId)
        setMemberError(err instanceof ApiError ? err.message : 'Unable to update role')
      }
    }
  }

  async function handleRemove(userId: string) {
    setMemberError(null)
    setMemberErrorUserId(null)
    try {
      await removeMember(userId)
      await loadAll()
    } catch (err) {
      if (err instanceof ApiError && err.code === 'last_admin') {
        setMemberErrorUserId(userId)
        setMemberError('A workspace must keep at least one admin.')
      } else {
        setMemberErrorUserId(userId)
        setMemberError(err instanceof ApiError ? err.message : 'Unable to remove member')
      }
    }
  }

  async function handleInvite(event: React.FormEvent) {
    event.preventDefault()
    setInviteError(null)
    setInviting(true)
    try {
      await createInvitation(inviteEmail, inviteRole)
      setInviteEmail('')
      setInviteRole('member')
      await loadAll()
    } catch (err) {
      if (err instanceof ApiError && (err.code === 'already_member' || err.code === 'invite_pending')) {
        setInviteError(err.message)
      } else {
        setInviteError(err instanceof ApiError ? err.message : 'Unable to send invitation')
      }
    } finally {
      setInviting(false)
    }
  }

  async function handleRevoke(id: string) {
    await revokeInvitation(id)
    await loadAll()
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <h1 className="mb-1 text-lg font-semibold">Settings</h1>
      <p className="mb-6 text-sm text-muted-foreground">Manage workspace members.</p>
      <SettingsNav />

      {loading && <p className="text-sm text-muted-foreground">Loading...</p>}

      {!loading && (
        <div className="space-y-8">
          <section>
            <h2 className="mb-3 text-sm font-semibold">Members</h2>
            <div className="space-y-2">
              {members.map((member) => (
                <Card key={member.user_id} className="flex items-center justify-between px-4 py-3">
                  <div>
                    <p className="text-sm font-medium">{member.full_name || member.email}</p>
                    <p className="text-xs text-muted-foreground">{member.email}</p>
                    {memberErrorUserId === member.user_id && memberError && (
                      <p className="mt-1 text-xs text-red-500">{memberError}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-3">
                    <Badge>{member.role}</Badge>
                    <select
                      className={selectClass}
                      value={member.role}
                      onChange={(e) =>
                        void handleRoleChange(member.user_id, e.target.value as 'admin' | 'member')
                      }
                    >
                      <option value="admin">admin</option>
                      <option value="member">member</option>
                    </select>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => void handleRemove(member.user_id)}
                    >
                      Remove
                    </Button>
                  </div>
                </Card>
              ))}
              {members.length === 0 && (
                <p className="text-sm text-muted-foreground">No members yet.</p>
              )}
            </div>
          </section>

          <section>
            <h2 className="mb-3 text-sm font-semibold">Invite someone</h2>
            <Card className="max-w-lg p-4">
              <form onSubmit={(e) => void handleInvite(e)} className="flex items-start gap-2">
                <div className="flex-1">
                  <Input
                    type="email"
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                    placeholder="Email"
                    required
                  />
                  {inviteError && <p className="mt-1 text-xs text-red-500">{inviteError}</p>}
                </div>
                <select
                  className={selectClass}
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value as 'admin' | 'member')}
                >
                  <option value="admin">admin</option>
                  <option value="member">member</option>
                </select>
                <Button type="submit" disabled={inviting}>
                  {inviting ? 'Sending...' : 'Invite'}
                </Button>
              </form>
            </Card>
          </section>

          <section>
            <h2 className="mb-3 text-sm font-semibold">Pending invitations</h2>
            <div className="space-y-2">
              {invitations.map((invitation) => (
                <Card key={invitation.id} className="flex items-center justify-between px-4 py-3">
                  <div>
                    <p className="text-sm font-medium">{invitation.email}</p>
                    <p className="text-xs text-muted-foreground">
                      Expires {new Date(invitation.expires_at).toLocaleString()}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <Badge>{invitation.role}</Badge>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => void handleRevoke(invitation.id)}
                    >
                      Revoke
                    </Button>
                  </div>
                </Card>
              ))}
              {invitations.length === 0 && (
                <p className="text-sm text-muted-foreground">No pending invitations.</p>
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  )
}
