import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  askAnalyticsFollowUp,
  exportExecutionCSV,
  getExecutionAnalytics,
  getExecutionCharts,
  type AnalyticsSummary,
  type ChartRecommendation,
  type ChartType,
  type SQLExecutionResult,
} from '../../api/client'
import { ExecutionInsights } from './ExecutionInsights'

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    askAnalyticsFollowUp: vi.fn(),
    exportExecutionCSV: vi.fn(),
    getExecutionAnalytics: vi.fn(),
    getExecutionCharts: vi.fn(),
  }
})

vi.mock('recharts', async () => {
  const React = await import('react')
  const chart = (type: string) =>
    function MockChart({ children }: { children?: React.ReactNode }) {
      return React.createElement(
        'div',
        { 'data-testid': `chart-${type}` },
        children,
      )
    }
  const empty = () => null
  return {
    Area: empty,
    AreaChart: chart('area'),
    Bar: empty,
    BarChart: chart('bar'),
    CartesianGrid: empty,
    Cell: empty,
    Legend: empty,
    Line: empty,
    LineChart: chart('line'),
    Pie: empty,
    PieChart: chart('pie'),
    ResponsiveContainer: chart('responsive'),
    Scatter: empty,
    ScatterChart: chart('scatter'),
    Tooltip: empty,
    XAxis: empty,
    YAxis: empty,
  }
})

const queryResult: SQLExecutionResult = {
  execution_id: 'exec-1',
  status: 'success',
  columns: [
    { name: 'category', data_type: 'TEXT' },
    { name: 'amount', data_type: 'REAL' },
  ],
  rows: [['books', 12], ['games', 7]],
  row_count: 2,
  execution_duration_ms: 4.2,
  truncated: false,
  error: null,
  validation_errors: [],
}

const summary: AnalyticsSummary = {
  execution_id: 'exec-1',
  row_count: 2,
  column_count: 2,
  truncated: false,
  columns: [
    {
      name: 'category',
      data_type: 'TEXT',
      non_null_count: 2,
      null_count: 0,
      distinct_count: 2,
      numeric_statistics: null,
      category_frequencies: [
        { value: 'books', count: 1 },
        { value: 'games', count: 1 },
      ],
      date_minimum: null,
      date_maximum: null,
      date_granularity: null,
      trend: [],
      grouped_summaries: [
        { category: 'books', value_column: 'amount', count: 1, total: '12', average: '12' },
        { category: 'games', value_column: 'amount', count: 1, total: '7', average: '7' },
      ],
    },
    {
      name: 'amount',
      data_type: 'REAL',
      non_null_count: 2,
      null_count: 0,
      distinct_count: 2,
      numeric_statistics: {
        minimum: '7',
        maximum: '12',
        mean: '9.5',
        median: '9.5',
        total: '19',
      },
      category_frequencies: [],
      date_minimum: null,
      date_maximum: null,
      date_granularity: null,
      trend: [],
      grouped_summaries: [],
    },
  ],
  observations: ['amount ranges from 7 to 12 across returned rows.'],
}

function recommendation(chartType: ChartType): ChartRecommendation {
  return {
    chart_type: chartType,
    title: `amount by category (${chartType})`,
    x_axis_column: 'category',
    y_axis_column: 'amount',
    grouping_column: null,
    explanation: 'A chart based on returned values.',
    required_data_fields: ['category', 'amount'],
    suitable: true,
    suitability_reason: 'Two categories and numeric values are available.',
    data: [
      { category: 'books', amount: 12 },
      { category: 'games', amount: 7 },
    ],
  }
}

function chartResponse(chartType: ChartType) {
  return {
    execution_id: 'exec-1',
    suitable: true,
    reason: null,
    recommendations: [recommendation(chartType)],
  }
}

async function prepareCharts(chartType: ChartType) {
  vi.mocked(getExecutionAnalytics).mockResolvedValue(summary)
  vi.mocked(getExecutionCharts).mockResolvedValue(chartResponse(chartType))
  render(<ExecutionInsights result={queryResult} />)
  fireEvent.click(screen.getByRole('tab', { name: 'Charts' }))
  return screen.findByTestId(`chart-${chartType}`)
}

afterEach(() => {
  vi.clearAllMocks()
})

describe('ExecutionInsights', () => {
  it.each(['bar', 'line', 'pie', 'area', 'scatter'] as const)(
    'renders the recommended %s visualization',
    async (chartType) => {
      await prepareCharts(chartType)
      expect(screen.getByText(`amount by category (${chartType})`)).toBeInTheDocument()
      expect(getExecutionCharts).toHaveBeenCalledWith('exec-1')
    },
  )

  it('switches between table and analytics summary views', async () => {
    vi.mocked(getExecutionAnalytics).mockResolvedValue(summary)
    vi.mocked(getExecutionCharts).mockResolvedValue(chartResponse('bar'))
    render(<ExecutionInsights result={queryResult} />)

    expect(screen.getByText('books')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: 'Analytics summary' }))

    expect(await screen.findByText('Returned rows')).toBeInTheDocument()
    expect(screen.getAllByText('9.5')).toHaveLength(2)
    expect(screen.getByText(/amount ranges from 7 to 12/)).toBeInTheDocument()
  })

  it('renders local date-trend summaries with their measures', async () => {
    const trendSummary: AnalyticsSummary = {
      ...summary,
      columns: summary.columns.map((column) =>
        column.name === 'category'
          ? {
              ...column,
              trend: [
                {
                  date: '2025-01',
                  value_column: 'amount',
                  total: '30',
                  average: '15',
                  count: 2,
                },
              ],
            }
          : column,
      ),
    }
    vi.mocked(getExecutionAnalytics).mockResolvedValue(trendSummary)
    vi.mocked(getExecutionCharts).mockResolvedValue(chartResponse('bar'))
    render(<ExecutionInsights result={queryResult} />)
    fireEvent.click(screen.getByRole('tab', { name: 'Analytics summary' }))

    const trendRow = (await screen.findByText('2025-01')).closest('tr')
    expect(trendRow).toHaveTextContent('amount')
    expect(trendRow).toHaveTextContent('30')
  })

  it('shows an explanatory empty state for unsuitable chart data', async () => {
    vi.mocked(getExecutionAnalytics).mockResolvedValue(summary)
    vi.mocked(getExecutionCharts).mockResolvedValue({
      execution_id: 'exec-1',
      suitable: false,
      reason: 'No suitable chart for these columns.',
      recommendations: [],
    })
    render(<ExecutionInsights result={queryResult} />)
    fireEvent.click(screen.getByRole('tab', { name: 'Charts' }))
    expect(await screen.findByText('No suitable chart for these columns.')).toBeInTheDocument()
  })

  it('shows cached-result API errors without hiding the table', async () => {
    vi.mocked(getExecutionAnalytics).mockRejectedValue(new Error('Result window expired.'))
    vi.mocked(getExecutionCharts).mockResolvedValue(chartResponse('bar'))
    render(<ExecutionInsights result={queryResult} />)
    fireEvent.click(screen.getByRole('tab', { name: 'Analytics summary' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Result window expired.')
    fireEvent.click(screen.getByRole('tab', { name: 'Table' }))
    expect(screen.getByText('books')).toBeInTheDocument()
  })

  it('downloads the cached result CSV and reports success', async () => {
    vi.mocked(getExecutionAnalytics).mockResolvedValue(summary)
    vi.mocked(getExecutionCharts).mockResolvedValue(chartResponse('bar'))
    vi.mocked(exportExecutionCSV).mockResolvedValue({
      blob: new Blob(['category,amount']),
      filename: 'sales.csv',
    })
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:test'),
    })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    render(<ExecutionInsights result={queryResult} />)

    fireEvent.click(screen.getByRole('button', { name: /Export CSV/ }))

    await waitFor(() => expect(exportExecutionCSV).toHaveBeenCalledWith('exec-1'))
    expect(await screen.findByRole('status')).toHaveTextContent('CSV downloaded.')
    expect(click).toHaveBeenCalled()
    click.mockRestore()
  })

  it('submits cached-result follow-up questions', async () => {
    vi.mocked(getExecutionAnalytics).mockResolvedValue(summary)
    vi.mocked(getExecutionCharts).mockResolvedValue(chartResponse('bar'))
    vi.mocked(askAnalyticsFollowUp).mockResolvedValue({
      execution_id: 'exec-1',
      answer: 'books has the highest amount total.',
      source: 'cached_result',
    })
    render(<ExecutionInsights result={queryResult} />)

    fireEvent.change(screen.getByLabelText('Ask about this result window'), {
      target: { value: 'Which category has the highest amount?' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))

    expect(await screen.findByText('books has the highest amount total.')).toBeInTheDocument()
    expect(askAnalyticsFollowUp).toHaveBeenCalledWith(
      'exec-1',
      'Which category has the highest amount?',
    )
  })
})
