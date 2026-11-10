import { useState } from 'react'
import { LogOut, Menu } from 'lucide-react'
import { Outlet, useLocation } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { useAuth } from '../../app/useAuth'

const routeTitles: Record<string, string> = {
  '/': 'Dashboard',
  '/assistant': 'AI Assistant',
  '/explorer': 'Database Explorer',
  '/sql-runner': 'SQL Runner',
  '/history': 'Query History',
  '/analytics': 'Analytics',
  '/saved-queries': 'Saved Queries',
  '/settings': 'Settings',
}

export function AppLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const { user, signOut } = useAuth()
  const location = useLocation()

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <a href="#main-content" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-white focus:px-4 focus:py-2">
        Skip to content
      </a>
      {sidebarOpen && (
        <button
          aria-label="Close navigation menu"
          className="fixed inset-0 z-30 bg-slate-950/50 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      <Sidebar open={sidebarOpen} onNavigate={() => setSidebarOpen(false)} />
      <div className="min-h-screen lg:pl-64">
        <header className="sticky top-0 z-20 flex h-16 items-center border-b border-slate-200 bg-white/90 px-4 backdrop-blur sm:px-8">
          <button
            aria-label="Open navigation menu"
            className="mr-3 rounded-lg p-2 text-slate-600 hover:bg-slate-100 lg:hidden"
            onClick={() => setSidebarOpen(true)}
          >
            <Menu size={20} />
          </button>
          <h1 className="text-sm font-semibold text-slate-800">
            {routeTitles[location.pathname] ?? 'Workspace'}
          </h1>
          <div className="ml-auto flex items-center gap-3">
            <span className="hidden max-w-48 truncate text-sm text-slate-500 sm:block">{user?.email}</span>
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-blue-100 text-sm font-semibold text-blue-700" aria-hidden="true">
              {user?.username.slice(0, 1).toUpperCase() ?? 'U'}
            </div>
            <button type="button" onClick={signOut} aria-label="Sign out" className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-800 lg:hidden">
              <LogOut size={17} />
            </button>
          </div>
        </header>
        <main id="main-content" className="mx-auto w-full max-w-7xl p-4 sm:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
