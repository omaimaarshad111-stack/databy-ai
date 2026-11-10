export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

let accessToken: string | null =
  typeof sessionStorage === 'undefined' ? null : sessionStorage.getItem('databy.accessToken')

export function setAccessToken(token: string | null): void {
  accessToken = token?.trim() || null
  if (typeof sessionStorage !== 'undefined') {
    if (accessToken) sessionStorage.setItem('databy.accessToken', accessToken)
    else sessionStorage.removeItem('databy.accessToken')
  }
}

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function expireSessionIfUnauthorized(response: Response): void {
  if (response.status === 401 && accessToken) {
    setAccessToken(null)
    window.dispatchEvent(new Event('databy-auth-expired'))
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (accessToken) {
    headers.set('Authorization', `Bearer ${accessToken}`)
  }

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers })
  expireSessionIfUnauthorized(response)
  if (!response.ok) {
    let message = `Request failed (${response.status}).`
    try {
      const body: unknown = await response.json()
      if (
        typeof body === 'object' &&
        body !== null &&
        'detail' in body &&
        typeof body.detail === 'string'
      ) {
        message = body.detail
      } else if (
        typeof body === 'object' &&
        body !== null &&
        'detail' in body &&
        Array.isArray(body.detail)
      ) {
        const messages = body.detail.flatMap((item: unknown) =>
          typeof item === 'object' &&
          item !== null &&
          'msg' in item &&
          typeof item.msg === 'string'
            ? [item.msg]
            : [],
        )
        if (messages.length > 0) message = messages.join(' ')
      }
    } catch {
      message = `Request failed (${response.status}).`
    }
    throw new ApiError(response.status, message)
  }

  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

export interface Connection {
  id: string
  name: string
  database_type: 'sqlite' | 'postgresql'
  connection_status: 'connected' | 'failed' | null
  last_tested_at: string | null
  metadata: Record<string, string | number>
  created_at: string
  updated_at: string
}

export interface UserProfile {
  id: string
  username: string
  email: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface AuthToken {
  access_token: string
  token_type: 'bearer'
}

export interface QueryHistoryItem {
  id: string
  connection_id: string
  connection_name: string
  database_type: 'sqlite' | 'postgresql'
  conversation_id: string | null
  natural_language_question: string
  generated_sql: string | null
  execution_status: 'pending' | 'succeeded' | 'failed' | 'cancelled'
  execution_duration_ms: number | null
  created_at: string
}

export interface QueryHistoryPage {
  items: QueryHistoryItem[]
  total: number
  page: number
  page_size: number
}

export interface SavedQuery {
  id: string
  connection_id: string
  connection_name: string
  database_type: 'sqlite' | 'postgresql'
  name: string
  description: string | null
  sql_query: string
  created_at: string
  updated_at: string
}

export interface SavedQueryInput {
  connection_id: string
  name: string
  description?: string | null
  sql_query: string
}

export function login(email: string, password: string): Promise<AuthToken> {
  return request('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
}

export function registerAccount(
  username: string,
  email: string,
  password: string,
): Promise<UserProfile> {
  return request('/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, email, password }),
  })
}

export function getCurrentUser(): Promise<UserProfile> {
  return request('/auth/me')
}

export interface SQLiteUploadResult {
  id: string
  name: string
  database_type: 'sqlite'
  connection_status: 'connected'
  last_tested_at: string
  created_at: string
}

export interface PostgreSQLInput {
  name: string
  host: string
  port: number
  database_name: string
  username: string
  password: string
  sslmode: 'require' | 'verify-ca' | 'verify-full' | 'prefer' | 'allow' | 'disable'
}

export interface ConnectionTest {
  success: boolean
  message: string
  last_tested_at: string
}

export interface DatabaseSchema {
  connection_id: string
  database_type: 'sqlite' | 'postgresql'
  schemas: Array<{
    name: string
    tables: Array<{
      name: string
      columns: Array<{
        name: string
        data_type: string
        nullable: boolean
        default: string | null
      }>
      primary_key: string[]
      foreign_keys: Array<{
        name: string | null
        columns: string[]
        referred_schema: string | null
        referred_table: string
        referred_columns: string[]
      }>
      unique_constraints: string[][]
      indexes: Array<{ name: string; columns: string[]; unique: boolean }>
    }>
  }>
}

export interface SQLValidationResult {
  is_valid: boolean
  database_dialect: 'sqlite' | 'postgresql'
  query_type: string | null
  validation_errors: string[]
  tables_used: string[]
}

export interface SQLExecutionColumn {
  name: string
  data_type: string | null
}

export interface SQLExecutionResult {
  execution_id: string
  status:
    | 'success'
    | 'failed'
    | 'timed_out'
    | 'rejected'
    | 'busy'
    | 'running'
    | 'results_expired'
  columns: SQLExecutionColumn[]
  rows: Array<Array<string | number | boolean | null>>
  row_count: number
  execution_duration_ms: number
  truncated: boolean
  error: string | null
  validation_errors: string[]
}

export interface NumericStatistics {
  minimum: string
  maximum: string
  mean: string
  median: string
  total: string
}

export interface CategoryFrequency {
  value: string | number | boolean | null
  count: number
}

export interface TrendPoint {
  date: string
  value_column: string
  total: string
  average: string
  count: number
}

export interface GroupSummary {
  category: string | number | boolean | null
  value_column: string
  count: number
  total: string
  average: string
}

export interface ColumnAnalytics {
  name: string
  data_type: string | null
  non_null_count: number
  null_count: number
  distinct_count: number
  numeric_statistics: NumericStatistics | null
  category_frequencies: CategoryFrequency[]
  date_minimum: string | null
  date_maximum: string | null
  date_granularity: 'day' | 'month' | null
  trend: TrendPoint[]
  grouped_summaries: GroupSummary[]
}

export interface AnalyticsSummary {
  execution_id: string
  row_count: number
  column_count: number
  truncated: boolean
  columns: ColumnAnalytics[]
  observations: string[]
}

export type ChartType = 'bar' | 'line' | 'pie' | 'area' | 'scatter'
export type ChartValue = string | number | boolean | null

export interface ChartRecommendation {
  chart_type: ChartType
  title: string
  x_axis_column: string
  y_axis_column: string
  grouping_column: string | null
  explanation: string
  required_data_fields: string[]
  suitable: boolean
  suitability_reason: string
  data: Array<Record<string, ChartValue>>
}

export interface ChartRecommendations {
  execution_id: string
  suitable: boolean
  reason: string | null
  recommendations: ChartRecommendation[]
}

export interface AnalyticsFollowUp {
  execution_id: string
  answer: string
  source: 'cached_result'
}

export interface ConversationSummary {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface ConversationMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  created_at: string
}

export interface ConversationDetail extends ConversationSummary {
  messages: ConversationMessage[]
}

export interface AssistantStep {
  name: string
  status: string
  message: string
}

export interface AssistantCompletion {
  conversation_id: string
  message: ConversationMessage
  intent: string | null
  steps: AssistantStep[]
  generated_sql: string | null
  validation_status: 'valid' | 'invalid' | 'not_run'
  validation_errors: string[]
  execution: SQLExecutionResult | null
  workflow_status: 'completed' | 'failed'
}

export interface AssistantProgress {
  name: string
  status: string
  message: string
}

export function listConnections(): Promise<Connection[]> {
  return request('/connections')
}

export function listQueryHistory(options: {
  page: number
  pageSize: number
  status?: QueryHistoryItem['execution_status'] | ''
  search?: string
}): Promise<QueryHistoryPage> {
  const params = new URLSearchParams({
    page: String(options.page),
    page_size: String(options.pageSize),
  })
  if (options.status) params.set('status', options.status)
  if (options.search?.trim()) params.set('search', options.search.trim())
  return request(`/history?${params.toString()}`)
}

export function listSavedQueries(search = ''): Promise<SavedQuery[]> {
  const params = new URLSearchParams()
  if (search.trim()) params.set('search', search.trim())
  const suffix = params.size ? `?${params.toString()}` : ''
  return request(`/saved-queries${suffix}`)
}

export function createSavedQuery(input: SavedQueryInput): Promise<SavedQuery> {
  return request('/saved-queries', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
}

export function updateSavedQuery(
  id: string,
  input: Partial<SavedQueryInput>,
): Promise<SavedQuery> {
  return request(`/saved-queries/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
}

export function deleteSavedQuery(id: string): Promise<void> {
  return request(`/saved-queries/${id}`, { method: 'DELETE' })
}

export function uploadSQLiteDatabase(name: string, file: File): Promise<SQLiteUploadResult> {
  const body = new FormData()
  body.set('name', name)
  body.set('file', file)
  return request('/connections/sqlite/upload', { method: 'POST', body })
}

export function testPostgreSQLConnection(input: PostgreSQLInput): Promise<ConnectionTest> {
  return request('/connections/postgresql/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
}

export function savePostgreSQLConnection(input: PostgreSQLInput): Promise<Connection> {
  return request('/connections/postgresql', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
}

export function testConnection(connectionId: string): Promise<ConnectionTest> {
  return request(`/connections/${connectionId}/test`, { method: 'POST' })
}

export function getConnectionSchema(connectionId: string): Promise<DatabaseSchema> {
  return request(`/connections/${connectionId}/schema`)
}

export function deleteConnection(connectionId: string): Promise<void> {
  return request(`/connections/${connectionId}`, { method: 'DELETE' })
}

export function validateSQL(
  connectionId: string,
  sqlQuery: string,
): Promise<SQLValidationResult> {
  return request('/sql/validate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ connection_id: connectionId, sql_query: sqlQuery }),
  })
}

export function executeSQL(
  connectionId: string,
  sqlQuery: string,
  pageSize?: number,
  offset = 0,
): Promise<SQLExecutionResult> {
  return request(`/connections/${connectionId}/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      sql_query: sqlQuery,
      offset,
      ...(pageSize === undefined ? {} : { page_size: pageSize }),
    }),
  })
}

export function getSQLExecution(executionId: string): Promise<SQLExecutionResult> {
  return request(`/executions/${executionId}`)
}

export function getExecutionAnalytics(executionId: string): Promise<AnalyticsSummary> {
  return request(`/executions/${executionId}/analytics`)
}

export function getExecutionCharts(executionId: string): Promise<ChartRecommendations> {
  return request(`/executions/${executionId}/charts`)
}

export function askAnalyticsFollowUp(
  executionId: string,
  question: string,
): Promise<AnalyticsFollowUp> {
  return request(`/executions/${executionId}/analytics/follow-up`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
}

export async function exportExecutionCSV(
  executionId: string,
): Promise<{ blob: Blob; filename: string }> {
  const headers = new Headers({ Accept: 'text/csv' })
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  const response = await fetch(
    `${API_BASE_URL}/executions/${executionId}/export/csv`,
    { headers },
  )
  expireSessionIfUnauthorized(response)
  if (!response.ok) {
    let message = `Request failed (${response.status}).`
    try {
      const body: unknown = await response.json()
      if (
        typeof body === 'object' &&
        body !== null &&
        'detail' in body &&
        typeof body.detail === 'string'
      ) {
        message = body.detail
      }
    } catch {
      message = `Request failed (${response.status}).`
    }
    throw new ApiError(response.status, message)
  }
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const filename = disposition.match(/filename="([^"]+)"/i)?.[1] ?? `databy-ai-${executionId}.csv`
  return { blob: await response.blob(), filename }
}

export function listConversations(): Promise<ConversationSummary[]> {
  return request('/assistant/conversations')
}

export function createConversation(title = 'New conversation'): Promise<ConversationSummary> {
  return request('/assistant/conversations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
}

export function getConversation(conversationId: string): Promise<ConversationDetail> {
  return request(`/assistant/conversations/${conversationId}`)
}

export async function sendAssistantMessage(
  conversationId: string,
  connectionId: string,
  content: string,
  onProgress: (progress: AssistantProgress) => void,
  signal?: AbortSignal,
): Promise<AssistantCompletion> {
  const headers = new Headers({
    Accept: 'text/event-stream',
    'Content-Type': 'application/json',
  })
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  const response = await fetch(
    `${API_BASE_URL}/assistant/conversations/${conversationId}/messages`,
    {
      method: 'POST',
      headers,
      body: JSON.stringify({ connection_id: connectionId, content }),
      signal,
    },
  )
  expireSessionIfUnauthorized(response)
  if (!response.ok) {
    let message = `Request failed (${response.status}).`
    try {
      const body: unknown = await response.json()
      if (
        typeof body === 'object' &&
        body !== null &&
        'detail' in body &&
        typeof body.detail === 'string'
      ) {
        message = body.detail
      }
    } catch {
      message = `Request failed (${response.status}).`
    }
    throw new ApiError(response.status, message)
  }
  if (!response.body) throw new Error('The assistant response stream is unavailable.')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let completion: AssistantCompletion | null = null
  let streamError: string | null = null

  function consumeEvent(rawEvent: string) {
    const lines = rawEvent.split(/\r?\n/)
    const eventName = lines.find((line) => line.startsWith('event:'))?.slice(6).trim()
    const data = lines
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trim())
      .join('\n')
    if (!data) return
    const payload: unknown = JSON.parse(data)
    if (eventName === 'progress') onProgress(payload as AssistantProgress)
    if (eventName === 'complete') completion = payload as AssistantCompletion
    if (eventName === 'error' && typeof payload === 'object' && payload !== null && 'message' in payload) {
      streamError = String(payload.message)
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const events = buffer.split(/\r?\n\r?\n/)
    buffer = events.pop() ?? ''
    for (const rawEvent of events) consumeEvent(rawEvent)
    if (done) break
  }
  if (streamError) throw new Error(streamError)
  if (!completion) throw new Error('The assistant response ended without a final result.')
  return completion
}
