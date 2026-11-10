import { useEffect, useState } from 'react'
import {
  ArrowRight,
  BarChart3,
  CheckCircle2,
  CircleAlert,
  Clock3,
  Database,
  MessageSquareText,
  PanelsTopLeft,
  Play,
  Plus,
  RefreshCw,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import {
  ApiError,
  listConnections,
  listConversations,
  listQueryHistory,
  listSavedQueries,
  type Connection,
  type ConversationSummary,
  type QueryHistoryItem,
} from '../../api/client'
import { useAuth } from '../../app/useAuth'
import { EmptyState } from '../../components/common/EmptyState'

function messageFor(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message
  return 'Workspace information could not be loaded.'
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

const quickActions = [
  { title: 'Connect a database', detail: 'Upload SQLite or add PostgreSQL', to: '/explorer', icon: Plus },
  { title: 'Ask the assistant', detail: 'Explore data with natural language', to: '/assistant', icon: MessageSquareText },
  { title: 'Run SQL', detail: 'Validate and run a read-only query', to: '/sql-runner', icon: Play },
  { title: 'Explore schema', detail: 'Browse tables and relationships', to: '/explorer', icon: Database },
]

export function DashboardPage() {
  const { user } = useAuth()
  const [connections, setConnections] = useState<Connection[]>([])
  const [recent, setRecent] = useState<QueryHistoryItem[]>([])
  const [queryCount, setQueryCount] = useState(0)
  const [savedCount, setSavedCount] = useState(0)
  const [recentConversations, setRecentConversations] = useState<ConversationSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')

  async function fetchWorkspace() {
    const [nextConnections, history, saved, conversations] = await Promise.all([
      listConnections(),
      listQueryHistory({ page: 1, pageSize: 5 }),
      listSavedQueries(),
      listConversations(),
    ])
    return {
      connections: nextConnections,
      history,
      saved,
      conversations: conversations.slice(0, 5),
    }
  }

  function applyWorkspace(workspace: Awaited<ReturnType<typeof fetchWorkspace>>) {
      setConnections(workspace.connections)
      setRecent(workspace.history.items)
      setQueryCount(workspace.history.total)
      setSavedCount(workspace.saved.length)
      setRecentConversations(workspace.conversations)
  }

  useEffect(() => {
    let active = true
    void fetchWorkspace()
      .then((workspace) => {
        if (active) applyWorkspace(workspace)
      })
      .catch((requestError: unknown) => {
        if (active) setError(messageFor(requestError))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [])

  async function refreshWorkspace() {
    setRefreshing(true)
    setError('')
    try {
      applyWorkspace(await fetchWorkspace())
    } catch (requestError) {
      setError(messageFor(requestError))
    } finally {
      setRefreshing(false)
    }
  }

  const metrics = [
    { label: 'Connections', value: connections.length, icon: Database, color: 'bg-blue-50 text-blue-700' },
    { label: 'Queries run', value: queryCount, icon: Clock3, color: 'bg-violet-50 text-violet-700' },
    { label: 'Saved queries', value: savedCount, icon: PanelsTopLeft, color: 'bg-emerald-50 text-emerald-700' },
    { label: 'Recent conversations', value: recentConversations.length, icon: MessageSquareText, color: 'bg-amber-50 text-amber-700' },
  ]

  return (
    <div className="space-y-8">
      <section className="flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
        <div>
          <p className="mb-2 text-sm font-medium text-blue-700">Workspace overview</p>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-950">
            Welcome, {user?.username}
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
            Your connected data sources, saved work, and recent query activity in one place.
          </p>
        </div>
        <button type="button" onClick={() => void refreshWorkspace()} disabled={refreshing} className="button-secondary">
          <RefreshCw size={15} className={refreshing ? 'animate-spin' : ''} />
          Refresh
        </button>
      </section>

      {error && <p role="alert" className="status-error">{error}</p>}

      <section aria-label="Workspace metrics" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {metrics.map(({ label, value, icon: Icon, color }) => (
          <article key={label} className="surface-card p-4 sm:p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-sm text-slate-500">{label}</p>
                {loading ? (
                  <div className="mt-3 h-7 w-14 animate-pulse rounded bg-slate-100" />
                ) : (
                  <p className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">{value}</p>
                )}
              </div>
              <div className={`rounded-lg p-2.5 ${color}`}><Icon size={18} /></div>
            </div>
          </article>
        ))}
      </section>

      <section>
        <div className="mb-4">
          <h2 className="text-base font-semibold text-slate-900">Quick actions</h2>
          <p className="mt-1 text-sm text-slate-500">Go directly to a workspace task.</p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {quickActions.map(({ title, detail, to, icon: Icon }) => (
            <Link key={title} to={to} className="group flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-4 transition hover:border-blue-200 hover:shadow-sm">
              <span className="rounded-lg bg-slate-100 p-2 text-slate-600 group-hover:bg-blue-50 group-hover:text-blue-700"><Icon size={17} /></span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold text-slate-900">{title}</span>
                <span className="mt-1 block text-xs leading-5 text-slate-500">{detail}</span>
              </span>
              <ArrowRight size={15} className="mt-1 shrink-0 text-slate-300 group-hover:text-blue-600" />
            </Link>
          ))}
        </div>
      </section>

      <section className="grid items-start gap-6 xl:grid-cols-[1.4fr_1fr]">
        <div className="surface-card overflow-hidden">
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
            <div>
              <h2 className="font-semibold text-slate-900">Recent query activity</h2>
              <p className="mt-1 text-xs text-slate-500">Execution metadata only; temporary results may expire.</p>
            </div>
            <Link to="/history" className="text-sm font-medium text-blue-700 hover:text-blue-800">View all</Link>
          </div>
          {loading ? (
            <div className="space-y-3 p-5" aria-label="Loading recent queries">
              {[0, 1, 2].map((item) => <div key={item} className="h-10 animate-pulse rounded bg-slate-100" />)}
            </div>
          ) : recent.length ? (
            <ul className="divide-y divide-slate-100">
              {recent.map((item) => (
                <li key={item.id} className="flex flex-wrap items-center gap-3 px-5 py-3.5">
                  {item.execution_status === 'succeeded'
                    ? <CheckCircle2 size={17} className="shrink-0 text-emerald-600" />
                    : <CircleAlert size={17} className="shrink-0 text-amber-600" />}
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-slate-800">{item.natural_language_question}</p>
                    <p className="mt-1 text-xs text-slate-500">{item.connection_name} · {formatDate(item.created_at)}</p>
                  </div>
                  <span className="text-xs capitalize text-slate-500">{item.execution_status}</span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="p-5">
              <EmptyState
                icon={BarChart3}
                title="No query activity yet"
                description="Run a validated query or ask the assistant; completed activity will appear here."
                action={<Link to={connections.length ? '/sql-runner' : '/explorer'} className="button-primary">{connections.length ? 'Run a query' : 'Connect a database'}</Link>}
              />
            </div>
          )}
        </div>

        <div className="surface-card overflow-hidden">
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
            <div>
              <h2 className="font-semibold text-slate-900">Database connections</h2>
              <p className="mt-1 text-xs text-slate-500">Connection metadata only; credentials are never shown.</p>
            </div>
            <Link to="/explorer" aria-label="Manage connections" className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"><ArrowRight size={16} /></Link>
          </div>
          {loading ? (
            <div className="space-y-3 p-5" aria-label="Loading connections">
              {[0, 1].map((item) => <div key={item} className="h-12 animate-pulse rounded bg-slate-100" />)}
            </div>
          ) : connections.length ? (
            <ul className="divide-y divide-slate-100">
              {connections.slice(0, 5).map((connection) => (
                <li key={connection.id} className="flex items-center gap-3 px-5 py-3.5">
                  <span className="rounded-lg bg-slate-100 p-2 text-slate-600"><Database size={16} /></span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-slate-800">{connection.name}</span>
                    <span className="block text-xs capitalize text-slate-500">{connection.database_type}</span>
                  </span>
                  <span className={`h-2 w-2 rounded-full ${connection.connection_status === 'connected' ? 'bg-emerald-500' : connection.connection_status === 'failed' ? 'bg-rose-500' : 'bg-slate-300'}`} title={connection.connection_status ?? 'Not tested'} />
                </li>
              ))}
            </ul>
          ) : (
            <div className="p-5">
              <EmptyState
                icon={Database}
                title="Connect a data source"
                description="Add PostgreSQL or upload SQLite to start exploring your own data."
                action={<Link to="/explorer" className="button-primary">Connect database</Link>}
              />
            </div>
          )}
        </div>
      </section>

      <section className="surface-card overflow-hidden">
        <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
          <div>
            <h2 className="font-semibold text-slate-900">Recent conversations</h2>
            <p className="mt-1 text-xs text-slate-500">Open a conversation in the assistant to continue the thread.</p>
          </div>
          <Link to="/assistant" className="text-sm font-medium text-blue-700 hover:text-blue-800">Open assistant</Link>
        </header>
        {loading ? (
          <div className="space-y-3 p-5" aria-label="Loading conversations">
            {[0, 1].map((item) => <div key={item} className="h-10 animate-pulse rounded bg-slate-100" />)}
          </div>
        ) : recentConversations.length ? (
          <ul className="divide-y divide-slate-100">
            {recentConversations.map((conversation) => (
              <li key={conversation.id}>
                <Link
                  to="/assistant"
                  state={{ conversationId: conversation.id }}
                  className="flex flex-wrap items-center gap-3 px-5 py-3.5 hover:bg-slate-50"
                >
                  <MessageSquareText size={16} className="shrink-0 text-slate-400" />
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-800">{conversation.title}</span>
                  <span className="text-xs text-slate-500">{formatDate(conversation.updated_at)}</span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <div className="p-5">
            <EmptyState icon={MessageSquareText} title="No conversations yet" description="Start a conversation in the AI Assistant to see it listed here." />
          </div>
        )}
      </section>
    </div>
  )
}
