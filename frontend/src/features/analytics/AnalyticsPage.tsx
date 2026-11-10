import { useEffect, useState } from 'react'
import { BarChart3, Database, LoaderCircle } from 'lucide-react'
import {
  ApiError,
  getSQLExecution,
  listQueryHistory,
  type QueryHistoryItem,
  type SQLExecutionResult,
} from '../../api/client'
import { EmptyState } from '../../components/common/EmptyState'
import { LazyExecutionInsights } from '../../components/charts/LazyExecutionInsights'

function messageFor(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message
  return 'The execution result could not be loaded.'
}

export function AnalyticsPage() {
  const [executions, setExecutions] = useState<QueryHistoryItem[]>([])
  const [executionId, setExecutionId] = useState('')
  const [result, setResult] = useState<SQLExecutionResult | null>(null)
  const [loadingList, setLoadingList] = useState(true)
  const [loadingResult, setLoadingResult] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    void listQueryHistory({ page: 1, pageSize: 100, status: 'succeeded' })
      .then((response) => {
        if (active) setExecutions(response.items)
      })
      .catch((requestError: unknown) => {
        if (active) setError(messageFor(requestError))
      })
      .finally(() => {
        if (active) setLoadingList(false)
      })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!executionId) return
    let active = true
    void getSQLExecution(executionId)
      .then((response) => {
        if (!active) return
        if (response.status === 'success') setResult(response)
        else setError(response.error ?? 'This execution no longer has a result window available.')
      })
      .catch((requestError: unknown) => {
        if (active) setError(messageFor(requestError))
      })
      .finally(() => {
        if (active) setLoadingResult(false)
      })
    return () => { active = false }
  }, [executionId])

  return (
    <div className="space-y-6">
      <header>
        <p className="mb-2 flex items-center gap-2 text-sm font-medium text-blue-700"><BarChart3 size={16} /> Insights</p>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-950">Analytics</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">
          Explore deterministic summaries and chart recommendations for recently completed query results.
          Only bounded results still in the temporary cache are available.
        </p>
      </header>

      <section className="surface-card p-4 sm:p-5">
        <label htmlFor="analytics-execution" className="mb-2 block text-sm font-medium text-slate-700">Successful execution</label>
        <select
          id="analytics-execution"
          value={executionId}
          disabled={loadingList || executions.length === 0}
          onChange={(event) => {
            const nextId = event.target.value
            setExecutionId(nextId)
            setResult(null)
            setError('')
            setLoadingResult(Boolean(nextId))
          }}
          className="form-input"
        >
          <option value="">Select a recent query result</option>
          {executions.map((item) => (
            <option key={item.id} value={item.id}>
              {item.natural_language_question} · {item.connection_name} · {new Date(item.created_at).toLocaleString()}
            </option>
          ))}
        </select>
        <p className="mt-2 text-xs leading-5 text-slate-500">
          Analytics describes the result window returned at execution time and does not rerun SQL.
        </p>
      </section>

      {error && <p role="status" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm leading-6 text-amber-900">{error}</p>}
      {loadingResult && <p className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500"><LoaderCircle size={17} className="animate-spin" />Loading the cached result…</p>}
      {result && <LazyExecutionInsights result={result} />}
      {!loadingList && !loadingResult && !executionId && executions.length === 0 && (
        <EmptyState
          icon={Database}
          title="No successful executions yet"
          description="Run a query in SQL Runner or the AI Assistant. Analytics will appear here while the result window is available."
        />
      )}
      {!loadingList && executionId && error && (
        <p className="text-xs text-slate-500">Run the query again in Query History to create a fresh bounded result window.</p>
      )}
    </div>
  )
}
