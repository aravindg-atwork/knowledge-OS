import { NavLink } from 'react-router-dom'
import { cn } from '@/lib/utils'

const tabClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
    isActive ? 'bg-muted text-foreground' : 'text-muted-foreground hover:bg-muted',
  )

export function SettingsNav() {
  return (
    <nav className="mb-6 flex gap-1 border-b border-border pb-3">
      <NavLink to="/settings/workspace" className={tabClass}>
        Workspace
      </NavLink>
      <NavLink to="/settings/members" className={tabClass}>
        Members
      </NavLink>
    </nav>
  )
}
