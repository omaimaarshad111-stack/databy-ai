import { useEffect, useState } from 'react'
import { ArrowUpRight, Database, KeyRound, LogOut, UserRound } from 'lucide-react'
import { Link } from 'react-router-dom'
import { ApiError, listConnections, type Connection } from '../../api/client'
import { useAuth } from '../../app/useAuth'
import { EmptyState } from '../../components/common/EmptyState'

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(value))
}

export function SettingsPage() {
  const { user, signOut } = useAuth()
  const [connections, setConnections] = useState<Connection[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    void listConnections()
      .then((response) => { if (active) setConnections(response) })
      .catch((requestError: unknown) => {
        if (active) {
          setError(requestError instanceof ApiError || requestError instanceof Error ? requestError.message : 'Settings could not be loaded.')
        }
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  return (
    <div className="space-y-6">
      <header>
        <p className="mb-2 flex items-center gap-2 text-sm font-medium text-blue-700"><KeyRound size={16} /> Account</p>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-950">Settings</h1>
        <p className="mt-2 text-sm leading-6 text-slate-500">Review your account and manage saved database connections.</p>
      </header>

      {error && <p role="alert" className="status-error">{error}</p>}

      <section className="surface-card overflow-hidden">
        <header className="flex items-center gap-3 border-b border-slate-100 px-5 py-4">
          <span className="rounded-lg bg-blue-50 p-2 text-blue-700"><UserRound size={17} /></span>
          <div><h2 className="font-semibold text-slate-900">Profile</h2><p className="text-xs text-slate-500">Account information from your authenticated session</p></div>
        </header>
        <dl className="grid gap-5 p-5 sm:grid-cols-2">
          <div><dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Username</dt><dd className="mt-1 text-sm text-slate-900">{user?.username}</dd></div>
          <div><dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Email</dt><dd className="mt-1 break-all text-sm text-slate-900">{user?.email}</dd></div>
          <div><dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Member since</dt><dd className="mt-1 text-sm text-slate-900">{user ? formatDate(user.created_at) : '—'}</dd></div>
          <div><dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Account status</dt><dd className="mt-1 text-sm capitalize text-slate-900">{user?.is_active ? 'Active' : 'Inactive'}</dd></div>
        </dl>
        <footer className="border-t border-slate-100 px-5 py-4">
          <button type="button" onClick={signOut} className="button-secondary text-rose-700"><LogOut size={15} />Sign out</button>
        </footer>
      </section>

      <section className="surface-card overflow-hidden">
        <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
          <div className="flex items-center gap-3">
            <span className="rounded-lg bg-slate-100 p-2 text-slate-700"><Database size={17} /></span>
            <div><h2 className="font-semibold text-slate-900">Database connections</h2><p className="text-xs text-slate-500">Credentials are never displayed here.</p></div>
          </div>
          <Link to="/explorer" className="button-secondary text-xs">Manage<ArrowUpRight size={14} /></Link>
        </header>
        {loading ? <div className="space-y-3 p-5" aria-label="Loading settings"><div className="h-10 animate-pulse rounded bg-slate-100" /><div className="h-10 animate-pulse rounded bg-slate-100" /></div> : connections.length ? (
          <ul className="divide-y divide-slate-100">
            {connections.map((connection) => (
              <li key={connection.id} className="flex flex-wrap items-center gap-3 px-5 py-4">
                <Database size={17} className="text-slate-400" />
                <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium text-slate-900">{connection.name}</span><span className="text-xs capitalize text-slate-500">{connection.database_type}</span></span>
                <span className="text-xs text-slate-500">{connection.connection_status ?? 'Not tested'}</span>
              </li>
            ))}
          </ul>
        ) : (
          <div className="p-5">
            <EmptyState icon={Database} title="No connections yet" description="Connect a data source to see its safe connection metadata here." action={<Link to="/explorer" className="button-primary">Open Database Explorer</Link>} />
          </div>
        )}
      </section>
      <p className="text-xs leading-5 text-slate-500">Password changes, email changes, and theme preferences are not currently exposed by the account API.</p>
    </div>
  )
}
