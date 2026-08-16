import { useEffect, useState } from 'react'
import { Outlet, useNavigate, NavLink } from 'react-router-dom'
import { MessageSquare, FileText, Moon, Sun, LogOut, Settings } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAuth } from './AuthContext'

function useDarkMode() {
  const [isDark, setIsDark] = useState(
    () => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false,
  )

  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDark)
  }, [isDark])

  return { isDark, toggle: () => setIsDark((prev) => !prev) }
}

export function AppShell() {
  const { isDark, toggle } = useDarkMode()
  const navigate = useNavigate()
  const { me, logout } = useAuth()

  function handleLogout() {
    logout()
    navigate('/login')
  }

  const navItemClass = ({ isActive }: { isActive: boolean }) =>
    cn(
      'flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors',
      isActive ? 'bg-muted text-foreground' : 'text-muted-foreground hover:bg-muted',
    )

  return (
    <div className="flex h-screen">
      <aside className="flex w-56 flex-col justify-between border-r border-border p-4">
        <div>
          <p className="mb-6 px-1 text-sm font-semibold">Knowledge Hub</p>
          <nav className="space-y-1">
            <NavLink to="/chat" className={navItemClass}>
              <MessageSquare size={16} /> Chat
            </NavLink>
            <NavLink to="/documents" className={navItemClass}>
              <FileText size={16} /> Documents
            </NavLink>
            {me?.role === 'admin' && (
              <NavLink to="/settings/workspace" className={navItemClass}>
                <Settings size={16} /> Settings
              </NavLink>
            )}
          </nav>
        </div>
        <div className="space-y-1">
          <button
            onClick={toggle}
            className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-muted"
          >
            {isDark ? <Sun size={16} /> : <Moon size={16} />}
            {isDark ? 'Light mode' : 'Dark mode'}
          </button>
          <button
            onClick={handleLogout}
            className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-muted"
          >
            <LogOut size={16} /> Sign out
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  )
}
