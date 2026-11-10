import { useEffect, useState, type FormEvent } from 'react'
import {
  Code2,
  Edit3,
  Play,
  Plus,
  Search,
  Trash2,
  X,
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import {
  ApiError,
  createSavedQuery,
  deleteSavedQuery,
  listConnections,
  listSavedQueries,
  updateSavedQuery,
  type Connection,
  type SavedQuery,
} from '../../api/client'
import { ConfirmDialog } from '../../components/common/ConfirmDialog'
import { EmptyState } from '../../components/common/EmptyState'

interface QueryForm {
  connection_id: string
  name: string
  description: string
  sql_query: string
}

const emptyForm: QueryForm = { connection_id: '', name: '', description: '', sql_query: '' }

function messageFor(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message
  return 'Saved queries could not be loaded.'
}

export function SavedQueriesPage() {
  const navigate = useNavigate()
  const [connections, setConnections] = useState<Connection[]>([])
  const [queries, setQueries] = useState<SavedQuery[]>([])
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editing, setEditing] = useState<SavedQuery | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [form, setForm] = useState<QueryForm>(emptyForm)
  const [deleting, setDeleting] = useState<SavedQuery | null>(null)

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [search])

  useEffect(() => {
    let active = true
    void Promise.all([listConnections(), listSavedQueries(debouncedSearch)])
      .then(([nextConnections, nextQueries]) => {
        if (!active) return
        setConnections(nextConnections)
        setQueries(nextQueries)
      })
      .catch((requestError: unknown) => {
        if (active) setError(messageFor(requestError))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [debouncedSearch])

  function startCreate() {
    setEditing(null)
    setForm({ ...emptyForm, connection_id: connections[0]?.id ?? '' })
    setError('')
    setFormOpen(true)
  }

  function startEdit(query: SavedQuery) {
    setEditing(query)
    setForm({
      connection_id: query.connection_id,
      name: query.name,
      description: query.description ?? '',
      sql_query: query.sql_query,
    })
    setError('')
    setFormOpen(true)
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!form.connection_id || busy) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      if (editing) {
        const updated = await updateSavedQuery(editing.id, {
          connection_id: form.connection_id,
          name: form.name.trim(),
          description: form.description.trim() || null,
          sql_query: form.sql_query.trim(),
        })
        setQueries((current) => current.map((item) => item.id === updated.id ? updated : item))
        setNotice('Saved query updated.')
      } else {
        const created = await createSavedQuery({
          connection_id: form.connection_id,
          name: form.name.trim(),
          description: form.description.trim() || null,
          sql_query: form.sql_query.trim(),
        })
        setQueries((current) => [created, ...current])
        setNotice('Query saved.')
      }
      setEditing(null)
      setFormOpen(false)
    } catch (requestError) {
      setError(messageFor(requestError))
    } finally {
      setBusy(false)
    }
  }

  async function confirmDelete() {
    if (!deleting) return
    setBusy(true)
    setError('')
    try {
      await deleteSavedQuery(deleting.id)
      setQueries((current) => current.filter((item) => item.id !== deleting.id))
      setNotice(`"${deleting.name}" was deleted.`)
      setDeleting(null)
    } catch (requestError) {
      setError(messageFor(requestError))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="mb-2 flex items-center gap-2 text-sm font-medium text-blue-700"><Code2 size={16} /> Query management</p>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-950">Saved queries</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">Keep SQL snippets with the connection they belong to. Every run still goes through server-side validation.</p>
        </div>
        <button type="button" onClick={startCreate} disabled={!connections.length} className="button-primary"><Plus size={16} />Save query</button>
      </header>

      {notice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
      {error && <p role="alert" className="status-error">{error}</p>}

      <label className="relative block">
        <span className="sr-only">Search saved queries</span>
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
        <input value={search} onChange={(event) => { setSearch(event.target.value); setLoading(true); setError('') }} placeholder="Search name, description, SQL, or connection…" className="form-input pl-9" />
      </label>

      {loading ? (
        <section className="space-y-3" aria-label="Loading saved queries">
          {[0, 1, 2].map((item) => <div key={item} className="h-36 animate-pulse rounded-2xl bg-slate-100" />)}
        </section>
      ) : queries.length ? (
        <section className="grid gap-4 lg:grid-cols-2">
          {queries.map((query) => (
            <article key={query.id} className="surface-card min-w-0 overflow-hidden">
              <header className="flex items-start gap-3 p-5">
                <span className="rounded-lg bg-blue-50 p-2 text-blue-700"><Code2 size={17} /></span>
                <div className="min-w-0 flex-1">
                  <h2 className="truncate font-semibold text-slate-900">{query.name}</h2>
                  <p className="mt-1 text-xs text-slate-500">{query.connection_name} · {query.database_type}</p>
                  {query.description && <p className="mt-2 text-sm leading-5 text-slate-600">{query.description}</p>}
                </div>
              </header>
              <pre className="mx-5 max-h-40 overflow-auto rounded-lg bg-slate-950 p-3 text-xs leading-5 text-slate-100">{query.sql_query}</pre>
              <footer className="flex flex-wrap justify-between gap-2 p-5">
                <div className="flex gap-2">
                  <button type="button" onClick={() => navigate('/sql-runner', { state: { connectionId: query.connection_id, query: query.sql_query } })} className="button-primary px-3 py-2 text-xs"><Play size={14} />Use in SQL Runner</button>
                  <button type="button" onClick={() => startEdit(query)} aria-label={`Edit ${query.name}`} className="button-secondary px-2.5 py-2"><Edit3 size={15} /></button>
                </div>
                <button type="button" onClick={() => setDeleting(query)} aria-label={`Delete ${query.name}`} className="rounded-lg border border-rose-200 p-2 text-rose-700 hover:bg-rose-50"><Trash2 size={15} /></button>
              </footer>
            </article>
          ))}
        </section>
      ) : (
        <EmptyState
          icon={Code2}
          title={search ? 'No matching saved queries' : 'No saved queries yet'}
          description={search ? 'Try another search term.' : connections.length ? 'Save a SQL statement to reuse it later.' : 'Connect a database before saving a query.'}
          action={connections.length > 0 && !search ? <button type="button" onClick={startCreate} className="button-primary"><Plus size={15} />Save your first query</button> : undefined}
        />
      )}

      {formOpen && (
        <div className="fixed inset-0 z-40 overflow-y-auto bg-slate-950/45 p-3 sm:p-8" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget && !busy) setFormOpen(false)
        }}>
          <section role="dialog" aria-modal="true" aria-labelledby="saved-query-form-title" className="mx-auto my-6 max-w-2xl rounded-2xl bg-white p-5 shadow-xl sm:p-7">
            <header className="mb-5 flex items-center justify-between gap-3">
              <div>
                <h2 id="saved-query-form-title" className="text-lg font-semibold text-slate-900">{editing ? 'Edit saved query' : 'Save a query'}</h2>
                <p className="mt-1 text-sm text-slate-500">The statement is validated again whenever it is executed.</p>
              </div>
              <button type="button" aria-label="Close saved query form" onClick={() => setFormOpen(false)} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"><X size={18} /></button>
            </header>
            <form onSubmit={(event) => void submit(event)} className="space-y-4">
              {error && <p role="alert" className="status-error">{error}</p>}
              <label className="block text-sm font-medium text-slate-700">Name<input required maxLength={160} value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} className="form-input mt-1.5" /></label>
              <label className="block text-sm font-medium text-slate-700">Database connection<select required value={form.connection_id} onChange={(event) => setForm((current) => ({ ...current, connection_id: event.target.value }))} className="form-input mt-1.5"><option value="">Select a connection</option>{connections.map((connection) => <option key={connection.id} value={connection.id}>{connection.name} · {connection.database_type}</option>)}</select></label>
              <label className="block text-sm font-medium text-slate-700">Description <span className="font-normal text-slate-400">(optional)</span><textarea rows={2} maxLength={2000} value={form.description} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} className="form-input mt-1.5" /></label>
              <label className="block text-sm font-medium text-slate-700">SQL<textarea required rows={8} spellCheck={false} value={form.sql_query} onChange={(event) => setForm((current) => ({ ...current, sql_query: event.target.value }))} className="form-input mt-1.5 font-mono text-xs leading-5" /></label>
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => setFormOpen(false)} disabled={busy} className="button-secondary">Cancel</button>
                <button type="submit" disabled={busy || !form.connection_id} className="button-primary">{busy ? 'Saving…' : editing ? 'Save changes' : 'Save query'}</button>
              </div>
            </form>
          </section>
        </div>
      )}
      <ConfirmDialog
        open={Boolean(deleting)}
        title="Delete saved query?"
        description={`"${deleting?.name ?? ''}" will be permanently removed from your saved queries.`}
        confirmLabel="Delete query"
        destructive
        busy={busy}
        onCancel={() => setDeleting(null)}
        onConfirm={() => void confirmDelete()}
      />
    </div>
  )
}
