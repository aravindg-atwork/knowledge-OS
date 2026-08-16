import { useEffect, useState } from 'react'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { ApiError } from '@/lib/apiClient'
import { useAuth } from '@/app/AuthContext'
import { SettingsNav } from './SettingsNav'
import { updateWorkspace } from './api/settingsApi'

export function WorkspaceSettingsPage() {
  const { me, refresh } = useAuth()
  const activeWorkspace = me?.workspaces.find((w) => w.id === me.active_workspace_id)
  const [name, setName] = useState(activeWorkspace?.name ?? '')
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setName(activeWorkspace?.name ?? '')
  }, [activeWorkspace?.name])

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setSaved(false)
    setSaving(true)
    try {
      await updateWorkspace(name)
      await refresh()
      setSaved(true)
    } catch (err) {
      if (err instanceof ApiError && err.code === 'invalid_workspace_name') {
        setError(err.message)
      } else {
        setError(err instanceof ApiError ? err.message : 'Unable to update workspace')
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mx-auto max-w-2xl px-6 py-8">
      <h1 className="mb-1 text-lg font-semibold">Settings</h1>
      <p className="mb-6 text-sm text-muted-foreground">Manage your workspace.</p>
      <SettingsNav />

      <Card className="max-w-md p-6">
        <h2 className="mb-4 text-sm font-semibold">Workspace name</h2>
        <form onSubmit={(e) => void handleSubmit(e)} className="space-y-3">
          <Input
            type="text"
            value={name}
            onChange={(e) => {
              setName(e.target.value)
              setSaved(false)
            }}
            placeholder="Workspace name"
            required
          />
          {error && <p className="text-sm text-red-500">{error}</p>}
          {saved && <p className="text-sm text-emerald-600">Workspace name updated.</p>}
          <Button type="submit" disabled={saving}>
            {saving ? 'Saving...' : 'Save'}
          </Button>
        </form>
      </Card>
    </div>
  )
}
