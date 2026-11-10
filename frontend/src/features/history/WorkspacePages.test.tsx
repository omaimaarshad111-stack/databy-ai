import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  createSavedQuery,
  deleteSavedQuery,
  getSQLExecution,
  listConnections,
  listConversations,
  listQueryHistory,
  listSavedQueries,
  updateSavedQuery,
} from '../../api/client'
import { DashboardPage } from '../dashboard/DashboardPage'
import { HistoryPage } from './HistoryPage'
import { SavedQueriesPage } from '../saved-queries/SavedQueriesPage'

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    createSavedQuery: vi.fn(),
    deleteSavedQuery: vi.fn(),
    getSQLExecution: vi.fn(),
    listConnections: vi.fn(),
    listConversations: vi.fn(),
    listQueryHistory: vi.fn(),
    listSavedQueries: vi.fn(),
    updateSavedQuery: vi.fn(),
  }
})

vi.mock('../../app/useAuth', () => ({
  useAuth: () => ({
    user: {
      id: 'user-1',
      username: 'data-user',
      email: 'data@example.com',
      is_active: true,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
  }),
}))

const connection = {
  id: 'conn-1',
  name: 'Reporting',
  database_type: 'sqlite' as const,
  connection_status: 'connected' as const,
  last_tested_at: null,
  metadata: {},
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const historyItem = {
  id: 'exec-1',
  connection_id: 'conn-1',
  connection_name: 'Reporting',
  database_type: 'sqlite' as const,
  conversation_id: null,
  natural_language_question: 'List revenue by month',
  generated_sql: 'SELECT [redacted] FROM sales',
  execution_status: 'succeeded' as const,
  execution_duration_ms: 12.5,
  created_at: '2026-10-10T10:00:00Z',
}

const savedQuery = {
  id: 'saved-1',
  connection_id: 'conn-1',
  connection_name: 'Reporting',
  database_type: 'sqlite' as const,
  name: 'Revenue report',
  description: 'Monthly revenue',
  sql_query: 'SELECT month, revenue FROM sales',
  created_at: '2026-10-01T00:00:00Z',
  updated_at: '2026-10-01T00:00:00Z',
}

function LocationState() {
  const location = useLocation()
  return <output data-testid="route-state">{JSON.stringify(location.state)}</output>
}

afterEach(() => {
  vi.clearAllMocks()
})

describe('workspace pages', () => {
  it('renders dashboard metrics from workspace APIs', async () => {
    vi.mocked(listConnections).mockResolvedValue([connection])
    vi.mocked(listConversations).mockResolvedValue([])
    vi.mocked(listQueryHistory).mockResolvedValue({
      items: [historyItem],
      total: 14,
      page: 1,
      page_size: 5,
    })
    vi.mocked(listSavedQueries).mockResolvedValue([savedQuery])

    render(<MemoryRouter><DashboardPage /></MemoryRouter>)

    expect(await screen.findByText('List revenue by month')).toBeInTheDocument()
    expect(screen.getByText('14')).toBeInTheDocument()
    expect(screen.getByText('Reporting')).toBeInTheDocument()
  })

  it('filters history and explains expired result windows', async () => {
    vi.mocked(listQueryHistory).mockResolvedValue({
      items: [historyItem],
      total: 1,
      page: 1,
      page_size: 20,
    })
    vi.mocked(getSQLExecution).mockResolvedValue({
      execution_id: 'exec-1',
      status: 'results_expired',
      columns: [],
      rows: [],
      row_count: 0,
      execution_duration_ms: 12.5,
      truncated: false,
      error: 'The result window expired.',
      validation_errors: [],
    })
    render(<MemoryRouter><HistoryPage /></MemoryRouter>)

    expect(await screen.findByText('List revenue by month')).toBeInTheDocument()
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'failed' } })
    await waitFor(() => expect(listQueryHistory).toHaveBeenLastCalledWith({
      page: 1,
      pageSize: 20,
      search: '',
      status: 'failed',
    }))
    fireEvent.click(screen.getByRole('button', { name: 'Details' }))

    expect(await screen.findByText(/temporary result window has expired/i)).toBeInTheDocument()
    expect(getSQLExecution).toHaveBeenCalledWith('exec-1')
  })

  it('creates saved queries and opens their SQL in the SQL Runner', async () => {
    vi.mocked(listConnections).mockResolvedValue([connection])
    vi.mocked(listSavedQueries).mockResolvedValue([])
    vi.mocked(createSavedQuery).mockResolvedValue(savedQuery)
    render(
      <MemoryRouter initialEntries={['/saved-queries']}>
        <Routes>
          <Route path="/saved-queries" element={<SavedQueriesPage />} />
          <Route path="/sql-runner" element={<LocationState />} />
        </Routes>
      </MemoryRouter>,
    )

    await screen.findByText('No saved queries yet')
    fireEvent.click(screen.getByRole('button', { name: /save your first query/i }))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Revenue report' } })
    fireEvent.change(screen.getByLabelText('Database connection'), { target: { value: 'conn-1' } })
    fireEvent.change(screen.getByLabelText('SQL'), { target: { value: 'SELECT month, revenue FROM sales' } })
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Save query' }))

    expect(await screen.findByText('Revenue report')).toBeInTheDocument()
    expect(createSavedQuery).toHaveBeenCalledWith({
      connection_id: 'conn-1',
      name: 'Revenue report',
      description: null,
      sql_query: 'SELECT month, revenue FROM sales',
    })

    fireEvent.click(screen.getByRole('button', { name: 'Use in SQL Runner' }))
    expect(await screen.findByTestId('route-state')).toHaveTextContent(
      JSON.stringify({ connectionId: 'conn-1', query: savedQuery.sql_query }),
    )
  })

  it('edits and confirms deletion of a saved query', async () => {
    vi.mocked(listConnections).mockResolvedValue([connection])
    vi.mocked(listSavedQueries).mockResolvedValue([savedQuery])
    vi.mocked(updateSavedQuery).mockResolvedValue({ ...savedQuery, name: 'Updated report' })
    vi.mocked(deleteSavedQuery).mockResolvedValue(undefined)
    render(<MemoryRouter><SavedQueriesPage /></MemoryRouter>)

    await screen.findByText('Revenue report')
    fireEvent.click(screen.getByRole('button', { name: 'Edit Revenue report' }))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Updated report' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText('Updated report')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Delete Updated report' }))
    expect(await screen.findByRole('dialog')).toHaveTextContent('permanently removed')
    fireEvent.click(screen.getByRole('button', { name: 'Delete query' }))
    await waitFor(() => expect(deleteSavedQuery).toHaveBeenCalledWith('saved-1'))
  })
})
