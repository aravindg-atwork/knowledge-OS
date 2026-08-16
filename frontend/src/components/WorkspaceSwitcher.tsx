import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDown, Plus } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ApiError } from '@/lib/apiClient'
import { useAuth } from '@/app/AuthContext'
import { createWorkspace } from '@/features/workspaces/api/workspacesApi'

export function WorkspaceSwitcher() {
  const { me, switchWorkspace } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  if (!me) return null

  const activeWorkspace =
    me.workspaces.find((w) => w.id === me.active_workspace_id) ?? me.workspaces[0]

  async function handleSwitch(workspaceId: string) {
    if (workspaceId === me?.active_workspace_id) {
      setOpen(false)
      return
    }
    setBusy(true)
    setError(null)
    try {
      await switchWorkspace(workspaceId)
      setOpen(false)
      // Staying on a document/chat page after switching would otherwise
      // keep showing state scoped to the previous tenant.
      navigate('/chat')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Unable to switch workspace')
    } finally {
      setBusy(false)
    }
  }

  async function handleCreate() {
    const name = window.prompt('Workspace name')
    if (!name) return
    setBusy(true)
    setError(null)
    try {
      const workspace = await createWorkspace(name)
      await switchWorkspace(workspace.id)
      setOpen(false)
      navigate('/chat')
    } catch (err) {
      if (err instanceof ApiError && err.code === 'invalid_workspace_name') {
        setError(err.message)
      } else {
        setError(err instanceof ApiError ? err.message : 'Unable to create workspace')
      }
    } finally {
      setBusy(false)
    }
  }

  if (me.workspaces.length === 1) {
    return <p className="px-1 text-sm font-semibold">{activeWorkspace?.name}</p>
  }

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="flex w-full items-center justify-between gap-2 rounded-md px-1 py-1 text-sm font-semibold hover:bg-muted"
      >
        <span className="truncate">{activeWorkspace?.name}</span>
        <ChevronDown size={14} className="shrink-0 text-muted-foreground" />
      </button>
      {open && (
        <div className="absolute left-0 top-full z-10 mt-1 w-56 rounded-md border border-border bg-card p-1 text-card-foreground shadow-lg">
          {me.workspaces.map((workspace) => (
            <button
              key={workspace.id}
              type="button"
              disabled={busy}
              onClick={() => void handleSwitch(workspace.id)}
              className={cn(
                'flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted disabled:opacity-50',
                workspace.id === me.active_workspace_id && 'bg-muted',
              )}
            >
              <span className="truncate">{workspace.name}</span>
              <span className="text-xs text-muted-foreground">{workspace.role}</span>
            </button>
          ))}
          <div className="my-1 border-t border-border" />
          <button
            type="button"
            disabled={busy}
            onClick={() => void handleCreate()}
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-muted-foreground hover:bg-muted disabled:opacity-50"
          >
            <Plus size={14} /> Create workspace
          </button>
          {error && <p className="px-2 pt-1 text-xs text-red-500">{error}</p>}
        </div>
      )}
    </div>
  )
}
