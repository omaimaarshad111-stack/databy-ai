import {
  BarChart3,
  Database,
  History,
  LayoutDashboard,
  LogOut,
  MessageSquareText,
  PanelsTopLeft,
  Settings,
  Terminal,
} from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { useAuth } from '../../app/useAuth'

const navigationSections = [
  {
    label: 'Workspace',
    links: [
      { label: 'Dashboard', to: '/', icon: LayoutDashboard },
      { label: 'AI Assistant', to: '/assistant', icon: MessageSquareText },
      { label: 'Database Explorer', to: '/explorer', icon: Database },
    ],
  },
  {
    label: 'Query management',
    links: [
      { label: 'SQL Runner', to: '/sql-runner', icon: Terminal },
      { label: 'Query History', to: '/history', icon: History },
      { label: 'Saved Queries', to: '/saved-queries', icon: PanelsTopLeft },
    ],
  },
  {
    label: 'Insights',
    links: [{ label: 'Analytics', to: '/analytics', icon: BarChart3 }],
  },
]

interface SidebarProps {
  open: boolean
  onNavigate: () => void
}

export function Sidebar({ open, onNavigate }: SidebarProps) {
  const { user, signOut } = useAuth()
  return (
    <aside
      className={`fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-slate-800 bg-slate-950 text-slate-300 transition-transform duration-200 lg:translate-x-0 ${
        open ? 'translate-x-0' : '-translate-x-full'
      }`}
    >
      <div className="flex h-16 shrink-0 items-center gap-3 border-b border-white/10 px-6">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-600 text-white">
          <Database size={19} strokeWidth={2.2} />
        </div>
        <span className="text-lg font-semibold tracking-tight text-white">
          databy<span className="text-blue-400">.ai</span>
        </span>
      </div>

      <nav aria-label="Main navigation" className="flex-1 space-y-7 overflow-y-auto px-3 py-6">
        {navigationSections.map((section) => (
          <section key={section.label} aria-label={section.label}>
            <h2 className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
              {section.label}
            </h2>
            <div className="space-y-1">
              {section.links.map(({ label, to, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === '/'}
                  onClick={onNavigate}
                  className={({ isActive }) =>
                    `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${
                      isActive
                        ? 'bg-blue-500/15 text-blue-300'
                        : 'text-slate-400 hover:bg-white/5 hover:text-white'
                    }`
                  }
                >
                  <Icon size={18} />
                  {label}
                </NavLink>
              ))}
            </div>
          </section>
        ))}
      </nav>

      <div className="border-t border-white/10 p-3">
        <NavLink
          to="/settings"
          onClick={onNavigate}
          className={({ isActive }) =>
            `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium ${
              isActive
                ? 'bg-blue-500/15 text-blue-300'
                : 'text-slate-400 hover:bg-white/5 hover:text-white'
            }`
          }
        >
          <Settings size={18} />
          Settings
        </NavLink>
        <div className="mt-2 flex items-center gap-3 rounded-lg px-3 py-2">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-800 text-xs font-semibold text-slate-200">
            {user?.username.slice(0, 1).toUpperCase() ?? 'U'}
          </div>
          <span className="min-w-0 flex-1 truncate text-sm text-slate-300">{user?.username}</span>
          <button
            type="button"
            onClick={() => {
              signOut()
              onNavigate()
            }}
            aria-label="Sign out"
            title="Sign out"
            className="rounded-md p-2 text-slate-400 hover:bg-white/10 hover:text-white focus-visible:outline-2 focus-visible:outline-blue-400"
          >
            <LogOut size={16} />
          </button>
        </div>
      </div>
    </aside>
  )
}
