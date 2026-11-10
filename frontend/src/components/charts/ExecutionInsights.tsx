import { useEffect, useState, type FormEvent } from 'react'
import {
  AlertCircle,
  BarChart3,
  Download,
  LoaderCircle,
  Table2,
} from 'lucide-react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  ApiError,
  askAnalyticsFollowUp,
  exportExecutionCSV,
  getExecutionAnalytics,
  getExecutionCharts,
  type AnalyticsFollowUp,
  type AnalyticsSummary,
  type ChartRecommendation,
  type ChartType,
  type SQLExecutionResult,
} from '../../api/client'

type View = 'table' | 'charts' | 'summary'

const chartColors = ['#2563eb', '#0d9488', '#7c3aed', '#ea580c', '#db2777', '#65a30d']

function messageFor(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return 'The analytics request could not be completed.'
}

function displayValue(value: string | number | boolean | null): string {
  return value === null ? 'NULL' : String(value)
}

function chartComponent(
  chart: ChartRecommendation,
  view: ChartType,
) {
  const commonAxis = (
    <>
      <CartesianGrid strokeDasharray="3 3" />
      <XAxis
        dataKey={chart.x_axis_column}
        name={chart.x_axis_column}
        tickFormatter={(value: string) =>
          value.length > 18 ? `${value.slice(0, 15)}…` : value
        }
        label={{
          value: chart.x_axis_column,
          position: 'insideBottom',
          offset: -4,
        }}
        height={55}
      />
      <YAxis
        dataKey={chart.y_axis_column}
        name={chart.y_axis_column}
        label={{
          value: chart.y_axis_column,
          angle: -90,
          position: 'insideLeft',
        }}
        width={70}
      />
      <Tooltip />
      <Legend />
    </>
  )

  if (view === 'bar') {
    return (
      <ResponsiveContainer width="100%" height={320}>
        <BarChart data={chart.data} margin={{ top: 12, right: 12, bottom: 20, left: 8 }}>
          {commonAxis}
          <Bar dataKey={chart.y_axis_column} fill={chartColors[0]} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    )
  }
  if (view === 'line') {
    return (
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={chart.data} margin={{ top: 12, right: 12, bottom: 20, left: 8 }}>
          {commonAxis}
          <Line
            type="monotone"
            dataKey={chart.y_axis_column}
            stroke={chartColors[0]}
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    )
  }
  if (view === 'area') {
    return (
      <ResponsiveContainer width="100%" height={320}>
        <AreaChart data={chart.data} margin={{ top: 12, right: 12, bottom: 20, left: 8 }}>
          {commonAxis}
          <Area
            type="monotone"
            dataKey={chart.y_axis_column}
            stroke={chartColors[1]}
            fill={chartColors[1]}
            fillOpacity={0.2}
          />
        </AreaChart>
      </ResponsiveContainer>
    )
  }
  if (view === 'scatter') {
    return (
      <ResponsiveContainer width="100%" height={320}>
        <ScatterChart margin={{ top: 12, right: 12, bottom: 20, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis
            dataKey={chart.x_axis_column}
            name={chart.x_axis_column}
            type="number"
            label={{ value: chart.x_axis_column, position: 'insideBottom', offset: -4 }}
          />
          <YAxis
            dataKey={chart.y_axis_column}
            name={chart.y_axis_column}
            type="number"
            label={{ value: chart.y_axis_column, angle: -90, position: 'insideLeft' }}
          />
          <Tooltip cursor={{ strokeDasharray: '3 3' }} />
          <Legend />
          <Scatter
            name={`${chart.x_axis_column} and ${chart.y_axis_column}`}
            data={chart.data}
            fill={chartColors[0]}
          />
        </ScatterChart>
      </ResponsiveContainer>
    )
  }
  return (
    <ResponsiveContainer width="100%" height={320}>
      <PieChart>
        <Pie
          data={chart.data}
          dataKey={chart.y_axis_column}
          nameKey={chart.x_axis_column}
          outerRadius={105}
          label={({ name, percent }) =>
            `${String(name).slice(0, 16)}${String(name).length > 16 ? '…' : ''} (${((percent ?? 0) * 100).toFixed(0)}%)`
          }
        >
          {chart.data.map((entry, index) => (
            <Cell
              key={String(entry[chart.x_axis_column])}
              fill={chartColors[index % chartColors.length]}
            />
          ))}
        </Pie>
        <Tooltip />
        <Legend />
      </PieChart>
    </ResponsiveContainer>
  )
}

function DataTable({ result }: { result: SQLExecutionResult }) {
  if (result.rows.length === 0) {
    return <p className="px-4 py-8 text-center text-sm text-slate-500">The query returned no rows.</p>
  }
  return (
    <div className="max-w-full overflow-auto">
      <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
        <thead className="bg-slate-50">
          <tr>
            {result.columns.map((column, index) => (
              <th
                key={`${column.name}-${index}`}
                scope="col"
                className="whitespace-nowrap px-4 py-3 font-semibold text-slate-700"
              >
                {column.name}
                {column.data_type && (
                  <span className="ml-1 font-normal text-slate-400">{column.data_type}</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {result.rows.map((row, rowIndex) => (
            <tr key={`${result.execution_id}-${rowIndex}`} className="hover:bg-slate-50">
              {row.map((value, columnIndex) => (
                <td
                  key={`${result.execution_id}-${rowIndex}-${columnIndex}`}
                  className="max-w-sm whitespace-pre-wrap break-words px-4 py-3 text-slate-600"
                >
                  {displayValue(value)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function AnalyticsSummaryView({ summary }: { summary: AnalyticsSummary }) {
  return (
    <div className="space-y-5 p-4 sm:p-5">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl bg-slate-50 p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Returned rows</p>
          <p className="mt-1 text-2xl font-semibold text-slate-900">{summary.row_count}</p>
        </div>
        <div className="rounded-xl bg-slate-50 p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Columns</p>
          <p className="mt-1 text-2xl font-semibold text-slate-900">{summary.column_count}</p>
        </div>
      </div>
      {summary.truncated && (
        <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
          These statistics describe only the bounded result window returned by the query.
        </p>
      )}
      <div className="space-y-3">
        {summary.columns.map((column) => (
          <article key={column.name} className="rounded-xl border border-slate-200 p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="font-semibold text-slate-900">{column.name}</h3>
              <span className="text-xs text-slate-500">
                {column.non_null_count} values · {column.null_count} NULL · {column.distinct_count} distinct
              </span>
            </div>
            {column.numeric_statistics && (
              <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
                {[
                  ['Minimum', column.numeric_statistics.minimum],
                  ['Maximum', column.numeric_statistics.maximum],
                  ['Mean', column.numeric_statistics.mean],
                  ['Median', column.numeric_statistics.median],
                  ['Sum', column.numeric_statistics.total],
                ].map(([label, value]) => (
                  <div key={label}>
                    <dt className="text-xs text-slate-500">{label}</dt>
                    <dd className="mt-0.5 font-medium text-slate-800">{value}</dd>
                  </div>
                ))}
              </dl>
            )}
            {column.date_minimum && column.date_maximum && (
              <p className="mt-3 text-sm text-slate-700">
                Date range: {column.date_minimum} – {column.date_maximum}
              </p>
            )}
            {column.trend.length > 0 && (
              <div className="mt-3 overflow-x-auto">
                <table className="min-w-full text-left text-xs">
                  <thead>
                    <tr className="text-slate-500">
                      <th className="py-1 pr-3">Date</th>
                      <th className="py-1 pr-3">Measure</th>
                      <th className="py-1 pr-3">Total</th>
                      <th className="py-1 pr-3">Average</th>
                      <th className="py-1">Rows</th>
                    </tr>
                  </thead>
                  <tbody>
                    {column.trend.map((point, index) => (
                      <tr key={`${point.date}-${point.value_column}-${index}`} className="border-t border-slate-100">
                        <td className="py-1.5 pr-3">{point.date}</td>
                        <td className="py-1.5 pr-3">{point.value_column}</td>
                        <td className="py-1.5 pr-3">{point.total}</td>
                        <td className="py-1.5 pr-3">{point.average}</td>
                        <td className="py-1.5">{point.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {column.category_frequencies.length > 0 && (
              <div className="mt-3">
                <p className="mb-1 text-xs font-medium text-slate-500">Most frequent returned categories</p>
                <ul className="flex flex-wrap gap-2">
                  {column.category_frequencies.map((frequency, index) => (
                    <li
                      key={`${String(frequency.value)}-${index}`}
                      className="max-w-full truncate rounded-full bg-blue-50 px-2.5 py-1 text-xs text-blue-800"
                    >
                      {String(frequency.value)} · {frequency.count}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {column.grouped_summaries.length > 0 && (
              <div className="mt-3 overflow-x-auto">
                <table className="min-w-full text-left text-xs">
                  <thead>
                    <tr className="text-slate-500">
                      <th className="py-1 pr-3">Category</th>
                      <th className="py-1 pr-3">Measure</th>
                      <th className="py-1 pr-3">Rows</th>
                      <th className="py-1 pr-3">Total</th>
                      <th className="py-1">Average</th>
                    </tr>
                  </thead>
                  <tbody>
                    {column.grouped_summaries.map((group, index) => (
                      <tr key={`${String(group.category)}-${group.value_column}-${index}`} className="border-t border-slate-100">
                        <td className="max-w-40 truncate py-1.5 pr-3">{String(group.category)}</td>
                        <td className="py-1.5 pr-3">{group.value_column}</td>
                        <td className="py-1.5 pr-3">{group.count}</td>
                        <td className="py-1.5 pr-3">{group.total}</td>
                        <td className="py-1.5">{group.average}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </article>
        ))}
      </div>
      {summary.observations.length > 0 && (
        <div>
          <h3 className="mb-2 font-semibold text-slate-900">Observations</h3>
          <ul className="list-disc space-y-1 pl-5 text-sm text-slate-600">
            {summary.observations.map((observation) => <li key={observation}>{observation}</li>)}
          </ul>
        </div>
      )}
    </div>
  )
}

export function ExecutionInsights({ result }: { result: SQLExecutionResult }) {
  const [view, setView] = useState<View>('table')
  const [analytics, setAnalytics] = useState<{
    executionId: string
    summary?: AnalyticsSummary
    charts?: Awaited<ReturnType<typeof getExecutionCharts>>
    error?: string
  } | null>(null)
  const [selectedChart, setSelectedChart] = useState(0)
  const [csvBusy, setCsvBusy] = useState(false)
  const [csvMessage, setCsvMessage] = useState('')
  const [followUpQuestion, setFollowUpQuestion] = useState('')
  const [followUp, setFollowUp] = useState<{
    executionId: string
    response: AnalyticsFollowUp
  } | null>(null)
  const [followUpBusy, setFollowUpBusy] = useState(false)
  const [followUpError, setFollowUpError] = useState<{
    executionId: string
    message: string
  } | null>(null)

  useEffect(() => {
    let active = true
    if (result.status !== 'success') return () => { active = false }

    void Promise.all([
      getExecutionAnalytics(result.execution_id),
      getExecutionCharts(result.execution_id),
    ])
      .then(([nextSummary, nextCharts]) => {
        if (!active) return
        setAnalytics({
          executionId: result.execution_id,
          summary: nextSummary,
          charts: nextCharts,
        })
      })
      .catch((requestError: unknown) => {
        if (active) {
          setAnalytics({
            executionId: result.execution_id,
            error: messageFor(requestError),
          })
        }
      })
    return () => { active = false }
  }, [result.execution_id, result.status])

  const currentAnalytics =
    analytics?.executionId === result.execution_id ? analytics : null
  const loading = result.status === 'success' && currentAnalytics === null
  const summary = currentAnalytics?.summary ?? null
  const charts = currentAnalytics?.charts ?? null
  const analyticsError = currentAnalytics?.error ?? ''
  const currentFollowUp =
    followUp?.executionId === result.execution_id ? followUp.response : null
  const currentFollowUpError =
    followUpError?.executionId === result.execution_id ? followUpError.message : ''
  const activeChartIndex =
    charts && selectedChart < charts.recommendations.length ? selectedChart : 0

  async function downloadCSV() {
    setCsvBusy(true)
    setCsvMessage('')
    try {
      const { blob, filename } = await exportExecutionCSV(result.execution_id)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = filename
      anchor.click()
      URL.revokeObjectURL(url)
      setCsvMessage('CSV downloaded.')
    } catch (requestError) {
      setCsvMessage(messageFor(requestError))
    } finally {
      setCsvBusy(false)
    }
  }

  async function submitFollowUp(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!followUpQuestion.trim()) return
    setFollowUpBusy(true)
    setFollowUp(null)
    setFollowUpError(null)
    try {
      setFollowUp({
        executionId: result.execution_id,
        response: await askAnalyticsFollowUp(result.execution_id, followUpQuestion.trim()),
      })
    } catch (requestError) {
      setFollowUpError({
        executionId: result.execution_id,
        message: messageFor(requestError),
      })
    } finally {
      setFollowUpBusy(false)
    }
  }

  const chart = charts?.recommendations[activeChartIndex]

  return (
    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-col gap-3 border-b border-slate-200 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">Query results</h2>
          <p className="mt-1 text-xs text-slate-500">
            {result.row_count} rows · {result.execution_duration_ms.toFixed(1)} ms
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {result.truncated && (
            <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-900">
              Bounded result window
            </span>
          )}
          <button
            type="button"
            onClick={() => void downloadCSV()}
            disabled={csvBusy || result.status !== 'success'}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            {csvBusy ? <LoaderCircle size={14} className="animate-spin" /> : <Download size={14} />}
            Export CSV
          </button>
        </div>
      </div>
      {result.error && (
        <div role="alert" className="border-b border-red-200 bg-red-50 px-5 py-3 text-sm text-red-800">
          {result.error}
          {result.validation_errors.length > 0 && (
            <ul className="mt-2 list-inside list-disc">
              {result.validation_errors.map((item) => <li key={item}>{item}</li>)}
            </ul>
          )}
        </div>
      )}
      {csvMessage && <p role="status" className="px-5 pt-3 text-sm text-slate-600">{csvMessage}</p>}

      <div role="tablist" aria-label="Query result views" className="flex gap-1 border-b border-slate-200 px-3 pt-3">
        {([
          ['table', 'Table', Table2],
          ['charts', 'Charts', BarChart3],
          ['summary', 'Analytics summary', BarChart3],
        ] as const).map(([key, label, Icon]) => (
          <button
            key={key}
            id={`result-tab-${key}`}
            type="button"
            role="tab"
            aria-selected={view === key}
            aria-controls="result-view-panel"
            onClick={() => setView(key)}
            className={`inline-flex items-center gap-2 rounded-t-lg px-3 py-2 text-xs font-medium ${
              view === key
                ? 'border-b-2 border-blue-600 text-blue-700'
                : 'text-slate-500 hover:bg-slate-50 hover:text-slate-800'
            }`}
          >
            <Icon size={15} />
            {label}
          </button>
        ))}
      </div>

      <div id="result-view-panel" role="tabpanel" aria-labelledby={`result-tab-${view}`}>
        {view === 'table' && <DataTable result={result} />}
        {view !== 'table' && result.status !== 'success' && (
          <p className="px-5 py-8 text-center text-sm text-slate-500">
            Analytics require a successful query result.
          </p>
        )}
        {view !== 'table' && result.status === 'success' && loading && (
          <p className="flex items-center justify-center gap-2 px-5 py-8 text-sm text-slate-500">
            <LoaderCircle size={16} className="animate-spin" /> Preparing local analytics…
          </p>
        )}
        {view !== 'table' && result.status === 'success' && analyticsError && (
          <p role="alert" className="flex items-start gap-2 px-5 py-8 text-sm text-red-700">
            <AlertCircle size={16} className="mt-0.5 shrink-0" />
            {analyticsError}
          </p>
        )}
        {view === 'charts' && charts && !loading && !analyticsError && (
          <div className="space-y-4 p-4 sm:p-5">
            {!charts.suitable || charts.recommendations.length === 0 ? (
              <p className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-sm text-slate-600">
                {charts.reason ?? 'No suitable chart is available for this result.'}
              </p>
            ) : (
              <>
                <div className="flex flex-wrap gap-2">
                  {charts.recommendations.map((recommendation, index) => (
                    <button
                      key={`${recommendation.chart_type}-${recommendation.title}`}
                      type="button"
                      aria-pressed={activeChartIndex === index}
                      onClick={() => setSelectedChart(index)}
                      className={`rounded-full border px-3 py-1.5 text-xs font-medium ${
                        selectedChart === index
                          ? 'border-blue-600 bg-blue-50 text-blue-700'
                          : 'border-slate-200 text-slate-600 hover:bg-slate-50'
                      }`}
                    >
                      {recommendation.chart_type} · {recommendation.title}
                    </button>
                  ))}
                </div>
                {chart && (
                  <article className="rounded-xl border border-slate-200 p-3 sm:p-4">
                    <h3 className="font-semibold text-slate-900">{chart.title}</h3>
                    <p className="mt-1 text-xs text-slate-500">{chart.explanation}</p>
                    <div className="mt-3 min-h-80 w-full">
                      {chartComponent(chart, chart.chart_type)}
                    </div>
                    <p className="text-center text-xs text-slate-500">{chart.suitability_reason}</p>
                  </article>
                )}
              </>
            )}
          </div>
        )}
        {view === 'summary' && summary && !loading && !analyticsError && (
          <AnalyticsSummaryView summary={summary} />
        )}
      </div>

      {result.status === 'success' && (
        <form onSubmit={(event) => void submitFollowUp(event)} className="border-t border-slate-200 p-4 sm:px-5">
          <label htmlFor={`analytics-follow-up-${result.execution_id}`} className="mb-2 block text-sm font-medium text-slate-800">
            Ask about this result window
          </label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              id={`analytics-follow-up-${result.execution_id}`}
              value={followUpQuestion}
              onChange={(event) => setFollowUpQuestion(event.target.value)}
              placeholder="e.g. Which category has the highest amount?"
              maxLength={2000}
              className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            />
            <button
              type="submit"
              disabled={followUpBusy || followUpQuestion.trim().length < 3}
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {followUpBusy ? 'Analyzing…' : 'Ask'}
            </button>
          </div>
          {currentFollowUp && <p role="status" className="mt-3 text-sm text-slate-700">{currentFollowUp.answer}</p>}
          {currentFollowUpError && <p role="alert" className="mt-3 text-sm text-red-700">{currentFollowUpError}</p>}
          <p className="mt-2 text-xs text-slate-500">
            Follow-ups use only the cached returned rows. If unavailable, continue in the assistant for a new validated query.
          </p>
        </form>
      )}
    </section>
  )
}
