import { useEffect, useState } from 'react'
import { AlertCircle, CheckCircle2, LoaderCircle, Play, ShieldCheck } from 'lucide-react'
import { useLocation } from 'react-router-dom'
import {
  ApiError,
  executeSQL,
  listConnections,
  validateSQL,
  type Connection,
  type SQLExecutionResult,
  type SQLValidationResult,
} from '../../api/client'
import { LazyExecutionInsights } from '../../components/charts/LazyExecutionInsights'

function messageFor(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return 'The request could not be completed.'
}

export function SQLRunnerPage() {
  const location = useLocation()
  const routeState = location.state as { connectionId?: string; query?: string } | null
  const [connections, setConnections] = useState<Connection[]>([])
  const [connectionId, setConnectionId] = useState(routeState?.connectionId ?? '')
  const [query, setQuery] = useState(routeState?.query ?? 'SELECT 1 AS connection_check')
  const [validation, setValidation] = useState<SQLValidationResult | null>(null)
  const [result, setResult] = useState<SQLExecutionResult | null>(null)
  const [busy, setBusy] = useState<'connections' | 'validate' | 'execute' | null>('connections')
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    void listConnections()
      .then((available) => {
        if (!active) return
        setConnections(available)
        setConnectionId((current) =>
          available.some((connection) => connection.id === current)
            ? current
            : (available[0]?.id ?? ''),
        )
      })
      .catch((requestError: unknown) => {
        if (active) setError(messageFor(requestError))
      })
      .finally(() => {
        if (active) setBusy(null)
      })
    return () => { active = false }
  }, [])

  async function validateQuery() {
    if (!connectionId) return
    setBusy('validate')
    setError('')
    setValidation(null)
    setResult(null)
    try {
      setValidation(await validateSQL(connectionId, query))
    } catch (requestError) {
      setError(messageFor(requestError))
    } finally {
      setBusy(null)
    }
  }

  async function executeQuery() {
    if (!connectionId || !validation?.is_valid) return
    setBusy('execute')
    setError('')
    setResult(null)
    try {
      setResult(await executeSQL(connectionId, query))
    } catch (requestError) {
      setError(messageFor(requestError))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <p className="mb-2 flex items-center gap-2 text-sm font-medium text-blue-700">
          <ShieldCheck size={16} />
          Read-only SQL
        </p>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-950">SQL Runner</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">
          Validate and run SELECT queries against a connected database. Queries are revalidated
          before execution and results are bounded.
        </p>
      </header>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <div className="mt-5 max-w-xl">
            <label htmlFor="sql-connection" className="mb-1.5 block text-sm font-medium text-slate-700">
              Database connection
            </label>
            <select
              id="sql-connection"
              value={connectionId}
              onChange={(event) => {
                setConnectionId(event.target.value)
                setValidation(null)
                setResult(null)
              }}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            >
              <option value="">Select a connection</option>
              {connections.map((connection) => (
                <option key={connection.id} value={connection.id}>
                  {connection.name} · {connection.database_type}
                </option>
              ))}
            </select>
            {connections.length === 0 && (
              <p className="mt-2 text-sm text-slate-500">Add a database connection before running a query.</p>
            )}
        </div>
      </section>

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-200 px-5 py-4 sm:px-6">
            <label htmlFor="sql-query" className="text-sm font-semibold text-slate-900">
              SQL query
            </label>
            <p className="mt-1 text-xs text-slate-500">Only validated read-only SELECT statements are accepted.</p>
          </div>
          <textarea
            id="sql-query"
            spellCheck={false}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setValidation(null)
              setResult(null)
            }}
            className="min-h-52 w-full resize-y border-0 bg-slate-950 px-5 py-4 font-mono text-sm leading-6 text-slate-100 outline-none focus:ring-2 focus:ring-inset focus:ring-blue-500"
          />
          <div className="flex flex-col gap-3 border-t border-slate-200 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <p className="text-xs text-slate-500">Maximum result page is controlled by the server.</p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => void validateQuery()}
                disabled={!connectionId || !query.trim() || busy !== null}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy === 'validate' && <LoaderCircle className="mr-2 inline animate-spin" size={15} />}
                Validate query
              </button>
              <button
                type="button"
                onClick={() => void executeQuery()}
                disabled={!connectionId || !validation?.is_valid || busy !== null}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy === 'execute' ? (
                  <LoaderCircle className="mr-2 inline animate-spin" size={15} />
                ) : (
                  <Play className="mr-2 inline" size={15} />
                )}
                Execute SELECT
              </button>
            </div>
          </div>

          {validation && (
            <div
              role="status"
              className={`border-t px-5 py-4 sm:px-6 ${
                validation.is_valid
                  ? 'border-emerald-200 bg-emerald-50'
                  : 'border-amber-200 bg-amber-50'
              }`}
            >
              <p className="flex items-center gap-2 text-sm font-medium">
                {validation.is_valid ? (
                  <CheckCircle2 className="text-emerald-700" size={17} />
                ) : (
                  <AlertCircle className="text-amber-700" size={17} />
                )}
                {validation.is_valid ? 'Read-only validation passed' : 'Validation rejected this query'}
              </p>
              {validation.validation_errors.length > 0 && (
                <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-amber-900">
                  {validation.validation_errors.map((item) => <li key={item}>{item}</li>)}
                </ul>
              )}
            </div>
          )}
      </section>

      {error && (
        <div role="alert" className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          <AlertCircle className="mt-0.5 shrink-0" size={17} />
          {error}
        </div>
      )}

      {result && <LazyExecutionInsights result={result} />}
    </div>
  )
}
