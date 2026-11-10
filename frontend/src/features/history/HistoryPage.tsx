import { useEffect, useRef, useState } from 'react'
import {
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Database,
  Eye,
  LoaderCircle,
  Search,
  X,
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import {
  ApiError,
  getSQLExecution,
  listQueryHistory,
  type QueryHistoryItem,
  type QueryHistoryPage as QueryHistoryPageData,
  type SQLExecutionResult,
} from '../../api/client'
import { EmptyState } from '../../components/common/EmptyState'
import { LazyExecutionInsights } from '../../components/charts/LazyExecutionInsights'

const pageSize = 20

function messageFor(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message
  return 'Query history could not be loaded.'
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function StatusBadge({ status }: { status: QueryHistoryItem['execution_status'] }) {
  const colors = status === 'succeeded'
    ? 'bg-emerald-50 text-emerald-700'
    : status === 'failed'
      ? 'bg-rose-50 text-rose-700'
      : 'bg-amber-50 text-amber-800'
  return <span className={`rounded-full px-2.5 py-1 text-xs font-medium capitalize ${colors}`}>{status}</span>
}

export function HistoryPage() {
  const navigate = useNavigate()
  const [history, setHistory] = useState<QueryHistoryPageData | null>(null)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<QueryHistoryItem['execution_status'] | ''>('')
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<QueryHistoryItem | null>(null)
  const [execution, setExecution] = useState<SQLExecutionResult | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')
  const detailRequest = useRef(0)
  const [debouncedSearch, setDebouncedSearch] = useState('')

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [search])

  useEffect(() => {
    let active = true
    void listQueryHistory({
      page,
      pageSize,
      search: debouncedSearch,
      status,
    })
      .then((response) => {
        if (active) setHistory(response)
      })
      .catch((requestError: unknown) => {
        if (active) setError(messageFor(requestError))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [page, status, debouncedSearch])

  async function showExecution(item: QueryHistoryItem) {
    const requestId = ++detailRequest.current
    setSelected(item)
    setExecution(null)
    setDetailError('')
    setDetailLoading(true)
    try {
      const result = await getSQLExecution(item.id)
      if (requestId !== detailRequest.current) return
      setExecution(result)
      if (result.status === 'results_expired') {
        setDetailError('The temporary result window has expired. Query metadata is retained, but the result data is not. Run the query again to view current results.')
      } else if (result.status !== 'success') {
        setDetailError(result.error ?? 'The result data is not available.')
      }
    } catch (requestError) {
      if (requestId === detailRequest.current) setDetailError(messageFor(requestError))
    } finally {
      if (requestId === detailRequest.current) setDetailLoading(false)
    }
  }

  const totalPages = Math.max(1, Math.ceil((history?.total ?? 0) / pageSize))

  return (
    <div className="space-y-6">
      <header>
        <p className="mb-2 flex items-center gap-2 text-sm font-medium text-blue-700"><Clock3 size={16} /> Query management</p>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-950">Query history</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">
          Search execution metadata and revisit results while their bounded, temporary result window remains available.
        </p>
      </header>

      <section className="surface-card p-4 sm:p-5">
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_200px]">
          <label className="relative block">
            <span className="sr-only">Search query history</span>
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); setLoading(true); setError('') }} placeholder="Search question, SQL, or database…" className="form-input pl-9" />
          </label>
          <label>
            <span className="sr-only">Filter by status</span>
            <select value={status} onChange={(event) => {
              const nextStatus = event.currentTarget.value
              if (nextStatus === '' || nextStatus === 'pending' || nextStatus === 'succeeded' || nextStatus === 'failed' || nextStatus === 'cancelled') {
                setStatus(nextStatus)
                setLoading(true)
                setError('')
              }
              setPage(1)
            }} className="form-input">
              <option value="">All statuses</option>
              <option value="succeeded">Succeeded</option>
              <option value="failed">Failed</option>
              <option value="pending">Pending</option>
              <option value="cancelled">Cancelled</option>
            </select>
          </label>
        </div>
      </section>

      {error && <p role="alert" className="status-error">{error}</p>}

      <section className="surface-card overflow-hidden">
        {loading ? (
          <div className="space-y-3 p-5" aria-label="Loading query history">
            {[0, 1, 2, 3].map((item) => <div key={item} className="h-14 animate-pulse rounded-lg bg-slate-100" />)}
          </div>
        ) : history?.items.length ? (
          <>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
                <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <tr>
                    <th scope="col" className="px-5 py-3">Query</th>
                    <th scope="col" className="px-5 py-3">Connection</th>
                    <th scope="col" className="px-5 py-3">Status</th>
                    <th scope="col" className="px-5 py-3">Duration</th>
                    <th scope="col" className="px-5 py-3">Date</th>
                    <th scope="col" className="px-5 py-3"><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {history.items.map((item) => (
                    <tr key={item.id} className="align-top hover:bg-slate-50/80">
                      <td className="max-w-sm px-5 py-4">
                        <p className="line-clamp-2 font-medium text-slate-900">{item.natural_language_question}</p>
                        <code className="mt-1 block truncate text-xs text-slate-500">{item.generated_sql ?? 'SQL unavailable'}</code>
                      </td>
                      <td className="whitespace-nowrap px-5 py-4 text-slate-600">
                        <span className="flex items-center gap-2"><Database size={15} className="text-slate-400" />{item.connection_name}</span>
                        <span className="ml-5 text-xs capitalize text-slate-400">{item.database_type}</span>
                      </td>
                      <td className="whitespace-nowrap px-5 py-4"><StatusBadge status={item.execution_status} /></td>
                      <td className="whitespace-nowrap px-5 py-4 text-slate-600">{item.execution_duration_ms === null ? '—' : `${item.execution_duration_ms.toFixed(1)} ms`}</td>
                      <td className="whitespace-nowrap px-5 py-4 text-slate-500">{formatDate(item.created_at)}</td>
                      <td className="whitespace-nowrap px-5 py-4">
                        <button type="button" onClick={() => void showExecution(item)} className="button-secondary px-2.5 py-1.5 text-xs">
                          <Eye size={14} /> Details
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex flex-col gap-3 border-t border-slate-100 px-5 py-3 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between">
              <p>{history.total} execution{history.total === 1 ? '' : 's'} · Page {page} of {totalPages}</p>
              <div className="flex gap-2">
                <button type="button" disabled={page <= 1} onClick={() => { setPage((current) => current - 1); setLoading(true); setError('') }} className="button-secondary px-2.5 py-1.5 text-xs"><ChevronLeft size={15} />Previous</button>
                <button type="button" disabled={page >= totalPages} onClick={() => { setPage((current) => current + 1); setLoading(true); setError('') }} className="button-secondary px-2.5 py-1.5 text-xs">Next<ChevronRight size={15} /></button>
              </div>
            </div>
          </>
        ) : (
          <div className="p-5">
            <EmptyState
              icon={Clock3}
              title={debouncedSearch || status ? 'No matching executions' : 'No queries yet'}
              description={debouncedSearch || status ? 'Try changing your search or status filter.' : 'Your read-only SQL and assistant executions will appear here.'}
            />
          </div>
        )}
      </section>

      {selected && (
        <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-950/45 p-3 sm:p-8" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) { detailRequest.current += 1; setSelected(null); setExecution(null) }
        }}>
          <section role="dialog" aria-modal="true" aria-labelledby="history-detail-title" className="mx-auto my-6 max-w-5xl rounded-2xl bg-slate-50 shadow-xl">
            <header className="flex items-start gap-4 border-b border-slate-200 bg-white p-5 sm:rounded-t-2xl sm:px-7">
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Execution detail</p>
                <h2 id="history-detail-title" className="mt-1 text-lg font-semibold text-slate-900">{selected.natural_language_question}</h2>
                <p className="mt-1 text-xs text-slate-500">{selected.connection_name} · {formatDate(selected.created_at)}</p>
              </div>
              <button type="button" aria-label="Close execution detail" onClick={() => { detailRequest.current += 1; setSelected(null); setExecution(null) }} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"><X size={18} /></button>
            </header>
            <div className="space-y-4 p-4 sm:p-6">
              <section className="rounded-xl border border-slate-200 bg-white p-4">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-sm font-semibold text-slate-800">Stored SQL</h3>
                  <button
                    type="button"
                    onClick={() => navigate('/sql-runner', { state: { connectionId: selected.connection_id, query: selected.generated_sql ?? '' } })}
                    disabled={!selected.generated_sql}
                    className="button-secondary px-2.5 py-1.5 text-xs"
                  >
                    <ArrowUpRight size={14} /> Open redacted SQL in runner
                  </button>
                </div>
                <p className="mt-1 text-xs leading-5 text-amber-800">String and numeric literals are redacted in history. Review and replace them before running.</p>
                <pre className="mt-3 overflow-x-auto rounded-lg bg-slate-950 p-3 text-xs leading-5 text-slate-100">{selected.generated_sql ?? 'No SQL was stored.'}</pre>
              </section>
              {detailLoading && <p className="flex items-center gap-2 text-sm text-slate-500"><LoaderCircle size={16} className="animate-spin" />Checking temporary result availability…</p>}
              {detailError && <p role="status" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm leading-6 text-amber-900">{detailError}</p>}
              {execution?.status === 'success' && <LazyExecutionInsights result={execution} />}
            </div>
          </section>
        </div>
      )}
    </div>
  )
}
