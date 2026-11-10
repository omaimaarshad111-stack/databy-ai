import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import {
  Check,
  ChevronDown,
  ChevronRight,
  Database,
  Eye,
  KeyRound,
  LoaderCircle,
  Plus,
  RefreshCw,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import {
  ApiError,
  deleteConnection,
  getConnectionSchema,
  listConnections,
  savePostgreSQLConnection,
  testConnection,
  testPostgreSQLConnection,
  uploadSQLiteDatabase,
  type Connection,
  type ConnectionTest,
  type DatabaseSchema,
  type PostgreSQLInput,
} from '../../api/client'
import { ConfirmDialog } from '../../components/common/ConfirmDialog'

const initialPostgresForm: PostgreSQLInput = {
  name: '',
  host: '',
  port: 5432,
  database_name: '',
  username: '',
  password: '',
  sslmode: 'require',
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return 'Something went wrong. Please try again.'
}

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : 'Not tested'
}

export function ConnectionsPage() {
  const [connections, setConnections] = useState<Connection[]>([])
  const [connectionsLoading, setConnectionsLoading] = useState(true)
  const [connectionsError, setConnectionsError] = useState('')
  const [notice, setNotice] = useState('')

  const [sqliteName, setSqliteName] = useState('')
  const [sqliteFile, setSqliteFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)

  const [postgresForm, setPostgresForm] = useState(initialPostgresForm)
  const [postgresBusy, setPostgresBusy] = useState<'test' | 'save' | null>(null)
  const [postgresResult, setPostgresResult] = useState<ConnectionTest | null>(null)

  const [testingId, setTestingId] = useState<string | null>(null)
  const [schema, setSchema] = useState<DatabaseSchema | null>(null)
  const [schemaConnection, setSchemaConnection] = useState('')
  const [schemaLoading, setSchemaLoading] = useState(false)
  const [schemaError, setSchemaError] = useState('')
  const [expandedTables, setExpandedTables] = useState<Set<string>>(new Set())
  const [deletingConnection, setDeletingConnection] = useState<Connection | null>(null)
  const [deleteBusy, setDeleteBusy] = useState(false)
  const schemaRequest = useRef(0)

  const refreshConnections = useCallback(async () => {
    try {
      setConnections(await listConnections())
    } catch (error) {
      setConnectionsError(errorMessage(error))
    } finally {
      setConnectionsLoading(false)
    }
  }, [])

  useEffect(() => {
    let active = true
    void listConnections()
      .then((available) => {
        if (active) setConnections(available)
      })
      .catch((error: unknown) => {
        if (active) setConnectionsError(errorMessage(error))
      })
      .finally(() => {
        if (active) setConnectionsLoading(false)
      })
    return () => { active = false }
  }, [])

  async function submitSQLiteUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!sqliteFile || !sqliteName.trim()) return
    setUploading(true)
    setNotice('')
    setConnectionsError('')
    setConnectionsLoading(true)
    try {
      await uploadSQLiteDatabase(sqliteName.trim(), sqliteFile)
      setSqliteName('')
      setSqliteFile(null)
      const input = document.getElementById('sqlite-file') as HTMLInputElement | null
      if (input) input.value = ''
      setNotice('SQLite database uploaded and inspected successfully.')
      await refreshConnections()
    } catch (error) {
      setConnectionsError(errorMessage(error))
    } finally {
      setUploading(false)
    }
  }

  function updatePostgresForm<K extends keyof PostgreSQLInput>(
    key: K,
    value: PostgreSQLInput[K],
  ) {
    setPostgresForm((current) => ({ ...current, [key]: value }))
    setPostgresResult(null)
  }

  async function testPostgresForm() {
    setPostgresBusy('test')
    setPostgresResult(null)
    setConnectionsError('')
    try {
      const result = await testPostgreSQLConnection(postgresForm)
      setPostgresResult(result)
    } catch (error) {
      setConnectionsError(errorMessage(error))
    } finally {
      setPostgresBusy(null)
    }
  }

  async function savePostgresForm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setPostgresBusy('save')
    setConnectionsError('')
    setNotice('')
    setConnectionsLoading(true)
    try {
      await savePostgreSQLConnection(postgresForm)
      setPostgresForm(initialPostgresForm)
      setPostgresResult(null)
      setNotice('PostgreSQL connection tested and saved.')
      await refreshConnections()
    } catch (error) {
      setConnectionsError(errorMessage(error))
    } finally {
      setPostgresBusy(null)
    }
  }

  async function runConnectionTest(connection: Connection) {
    setTestingId(connection.id)
    setConnectionsError('')
    try {
      const result = await testConnection(connection.id)
      setNotice(result.message)
      setConnectionsLoading(true)
      await refreshConnections()
    } catch (error) {
      setConnectionsError(errorMessage(error))
    } finally {
      setTestingId(null)
    }
  }

  async function showSchema(connection: Connection) {
    const requestId = ++schemaRequest.current
    setSchemaConnection(connection.id)
    setSchema(null)
    setSchemaError('')
    setSchemaLoading(true)
    try {
      const response = await getConnectionSchema(connection.id)
      if (requestId === schemaRequest.current) setSchema(response)
    } catch (error) {
      if (requestId === schemaRequest.current) setSchemaError(errorMessage(error))
    } finally {
      if (requestId === schemaRequest.current) setSchemaLoading(false)
    }
  }

  async function confirmRemoveConnection() {
    if (!deletingConnection) return
    const connection = deletingConnection
    setDeleteBusy(true)
    setConnectionsError('')
    setNotice('')
    try {
      await deleteConnection(connection.id)
      if (schemaConnection === connection.id) {
        schemaRequest.current += 1
        setSchema(null)
        setSchemaConnection('')
      }
      setNotice(`"${connection.name}" was deleted.`)
      setDeletingConnection(null)
      await refreshConnections()
    } catch (error) {
      setConnectionsError(errorMessage(error))
    } finally {
      setDeleteBusy(false)
    }
  }

  function toggleTable(key: string) {
    setExpandedTables((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  return (
    <div className="space-y-8">
      <section>
        <p className="mb-2 flex items-center gap-2 text-sm font-medium text-blue-700">
          <Database size={16} />
          Data sources
        </p>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-950">
          Database connections
        </h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">
          Connect PostgreSQL or upload SQLite, inspect schemas, and safely manage your data sources.
        </p>
      </section>

      {notice && (
        <div role="status" className="flex items-center gap-2 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">
          <Check size={17} />
          {notice}
        </div>
      )}
      {connectionsError && (
        <div role="alert" className="flex items-start gap-2 rounded-lg bg-rose-50 p-3 text-sm text-rose-800">
          <X className="mt-0.5 shrink-0" size={17} />
          <span>{connectionsError}</span>
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-2">
            <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
              <div className="mb-5 flex items-center gap-3">
                <div className="rounded-lg bg-blue-50 p-2 text-blue-700">
                  <Upload size={19} />
                </div>
                <div>
                  <h2 className="font-semibold text-slate-900">Upload SQLite database</h2>
                  <p className="mt-0.5 text-xs text-slate-500">.db, .sqlite, or .sqlite3</p>
                </div>
              </div>
              <form onSubmit={submitSQLiteUpload} className="space-y-4">
                <Field label="Connection name">
                  <input
                    required
                    maxLength={120}
                    value={sqliteName}
                    onChange={(event) => setSqliteName(event.target.value)}
                    className={inputClass}
                    placeholder="e.g. Local analytics"
                  />
                </Field>
                <Field label="Database file">
                  <input
                    id="sqlite-file"
                    required
                    type="file"
                    accept=".db,.sqlite,.sqlite3"
                    onChange={(event) => setSqliteFile(event.target.files?.[0] ?? null)}
                    className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-2 file:text-sm file:font-medium file:text-slate-700 hover:file:bg-slate-200"
                  />
                </Field>
                <p className="text-xs text-slate-500">
                  Uploads are size-limited, validated, stored under a server-generated name, and
                  opened read-only.
                </p>
                <button
                  type="submit"
                  disabled={uploading || !sqliteFile || !sqliteName.trim()}
                  className={primaryButtonClass}
                >
                  {uploading ? <LoaderCircle className="animate-spin" size={17} /> : <Upload size={17} />}
                  {uploading ? 'Uploading and validating…' : 'Upload database'}
                </button>
              </form>
            </section>

            <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
              <div className="mb-5 flex items-center gap-3">
                <div className="rounded-lg bg-indigo-50 p-2 text-indigo-700">
                  <Database size={19} />
                </div>
                <div>
                  <h2 className="font-semibold text-slate-900">Connect PostgreSQL</h2>
                  <p className="mt-0.5 text-xs text-slate-500">Credentials are encrypted at rest</p>
                </div>
              </div>
              <form onSubmit={savePostgresForm} className="space-y-4">
                <Field label="Connection name">
                  <input
                    required
                    value={postgresForm.name}
                    onChange={(event) => updatePostgresForm('name', event.target.value)}
                    className={inputClass}
                    placeholder="e.g. Reporting database"
                  />
                </Field>
                <div className="grid gap-3 sm:grid-cols-[1fr_110px]">
                  <Field label="Host">
                    <input
                      required
                      value={postgresForm.host}
                      onChange={(event) => updatePostgresForm('host', event.target.value)}
                      className={inputClass}
                      placeholder="db.example.com"
                    />
                  </Field>
                  <Field label="Port">
                    <input
                      required
                      type="number"
                      min={1}
                      max={65535}
                      value={postgresForm.port}
                      onChange={(event) => updatePostgresForm('port', Number(event.target.value))}
                      className={inputClass}
                    />
                  </Field>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Database">
                    <input
                      required
                      value={postgresForm.database_name}
                      onChange={(event) => updatePostgresForm('database_name', event.target.value)}
                      className={inputClass}
                    />
                  </Field>
                  <Field label="Username">
                    <input
                      required
                      autoComplete="username"
                      value={postgresForm.username}
                      onChange={(event) => updatePostgresForm('username', event.target.value)}
                      className={inputClass}
                    />
                  </Field>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Password">
                    <input
                      required
                      type="password"
                      autoComplete="new-password"
                      value={postgresForm.password}
                      onChange={(event) => updatePostgresForm('password', event.target.value)}
                      className={inputClass}
                    />
                  </Field>
                  <Field label="TLS mode">
                    <select
                      value={postgresForm.sslmode}
                      onChange={(event) =>
                        updatePostgresForm('sslmode', event.target.value as PostgreSQLInput['sslmode'])
                      }
                      className={inputClass}
                    >
                      <option value="require">Require TLS</option>
                      <option value="verify-full">Verify certificate and host</option>
                      <option value="verify-ca">Verify certificate</option>
                      <option value="prefer">Prefer TLS</option>
                      <option value="allow">Allow TLS</option>
                      <option value="disable">Disable TLS</option>
                    </select>
                  </Field>
                </div>
                {postgresResult && (
                  <p role="status" className="text-sm text-emerald-700">
                    {postgresResult.message}
                  </p>
                )}
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => void testPostgresForm()}
                    disabled={postgresBusy !== null || !postgresForm.password}
                    className={secondaryButtonClass}
                  >
                    {postgresBusy === 'test' ? (
                      <LoaderCircle className="animate-spin" size={16} />
                    ) : (
                      <RefreshCw size={16} />
                    )}
                    Test connection
                  </button>
                  <button
                    type="submit"
                    disabled={postgresBusy !== null || !postgresForm.password}
                    className={primaryButtonClass}
                  >
                    {postgresBusy === 'save' ? (
                      <LoaderCircle className="animate-spin" size={16} />
                    ) : (
                      <Plus size={16} />
                    )}
                    Test and save
                  </button>
                </div>
              </form>
            </section>
          </div>

          <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="flex flex-col gap-3 border-b border-slate-100 p-5 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="font-semibold text-slate-900">Your connections</h2>
                <p className="mt-1 text-sm text-slate-500">
                  Connection status is shown only after a real connection test.
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setConnectionsLoading(true)
                  setConnectionsError('')
                  void refreshConnections()
                }}
                disabled={connectionsLoading}
                className={secondaryButtonClass}
              >
                <RefreshCw className={connectionsLoading ? 'animate-spin' : ''} size={16} />
                Refresh
              </button>
            </div>
            {connectionsLoading ? (
              <LoadingState label="Loading connections…" />
            ) : connections.length === 0 ? (
              <div className="px-5 py-10 text-center">
                <Database className="mx-auto text-slate-300" size={28} />
                <p className="mt-3 text-sm font-medium text-slate-700">No saved connections</p>
                <p className="mt-1 text-sm text-slate-500">Upload a SQLite file or connect PostgreSQL to begin.</p>
              </div>
            ) : (
              <ul className="divide-y divide-slate-100">
                {connections.map((connection) => (
                  <li
                    key={connection.id}
                    className="flex flex-col gap-4 p-5 lg:flex-row lg:items-center lg:justify-between"
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <div className="rounded-lg bg-slate-100 p-2.5 text-slate-600">
                        <Database size={18} />
                      </div>
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-slate-900">{connection.name}</p>
                        <p className="mt-1 text-xs text-slate-500">
                          {connection.database_type === 'postgresql' ? 'PostgreSQL' : 'SQLite'}
                          {connection.metadata.host ? ` · ${connection.metadata.host}` : ''}
                          {' · Tested '}
                          {formatDate(connection.last_tested_at)}
                        </p>
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <ConnectionStatus status={connection.connection_status} />
                      <button
                        type="button"
                        onClick={() => void showSchema(connection)}
                        className={secondaryButtonClass}
                      >
                        <Eye size={16} />
                        Schema
                      </button>
                      <button
                        type="button"
                        onClick={() => void runConnectionTest(connection)}
                        disabled={testingId === connection.id}
                        className={secondaryButtonClass}
                      >
                        {testingId === connection.id ? (
                          <LoaderCircle className="animate-spin" size={16} />
                        ) : (
                          <RefreshCw size={16} />
                        )}
                        Test
                      </button>
                      <button
                        type="button"
                        aria-label={`Delete ${connection.name}`}
                        onClick={() => setDeletingConnection(connection)}
                        className="rounded-lg border border-rose-200 p-2 text-rose-700 hover:bg-rose-50"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {(schemaLoading || schema || schemaError) && (
            <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
              <div className="border-b border-slate-100 p-5">
                <h2 className="font-semibold text-slate-900">Schema explorer</h2>
                <p className="mt-1 text-sm text-slate-500">
                  Metadata only. Table contents are not retrieved.
                </p>
              </div>
              {schemaLoading ? (
                <LoadingState label="Inspecting database schema…" />
              ) : schemaError ? (
                <p role="alert" className="p-5 text-sm text-rose-700">{schemaError}</p>
              ) : schema ? (
                schema.schemas.length === 0 ||
                schema.schemas.every((item) => item.tables.length === 0) ? (
                  <p className="p-5 text-sm text-slate-500">No tables were found in this database.</p>
                ) : (
                  <div className="space-y-5 p-5">
                    {schema.schemas.map((schemaItem) => (
                      <div key={schemaItem.name}>
                        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                          Schema: {schemaItem.name}
                        </h3>
                        <div className="space-y-2">
                          {schemaItem.tables.map((table) => {
                            const key = `${schemaItem.name}.${table.name}`
                            const expanded = expandedTables.has(key)
                            return (
                              <div key={key} className="overflow-hidden rounded-lg border border-slate-200">
                                <button
                                  type="button"
                                  aria-expanded={expanded}
                                  onClick={() => toggleTable(key)}
                                  className="flex w-full items-center gap-2 bg-slate-50 px-3 py-3 text-left hover:bg-slate-100"
                                >
                                  {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                                  <Database size={15} className="text-slate-500" />
                                  <span className="text-sm font-medium text-slate-800">{table.name}</span>
                                  <span className="ml-auto text-xs text-slate-500">
                                    {table.columns.length} columns
                                  </span>
                                </button>
                                {expanded && (
                                  <div className="overflow-x-auto">
                                    <table className="w-full text-left text-xs">
                                      <thead className="bg-white text-slate-500">
                                        <tr>
                                          <th className="px-3 py-2 font-medium">Column</th>
                                          <th className="px-3 py-2 font-medium">Type</th>
                                          <th className="px-3 py-2 font-medium">Properties</th>
                                        </tr>
                                      </thead>
                                      <tbody className="divide-y divide-slate-100">
                                        {table.columns.map((column) => {
                                          const isPrimary = table.primary_key.includes(column.name)
                                          const foreignKey = table.foreign_keys.find((fk) =>
                                            fk.columns.includes(column.name),
                                          )
                                          const isUnique = table.unique_constraints.some((fields) =>
                                            fields.includes(column.name),
                                          )
                                          return (
                                            <tr key={column.name}>
                                              <td className="whitespace-nowrap px-3 py-2 font-medium text-slate-800">
                                                {column.name}
                                              </td>
                                              <td className="whitespace-nowrap px-3 py-2 font-mono text-slate-600">
                                                {column.data_type}
                                              </td>
                                              <td className="px-3 py-2 text-slate-500">
                                                <span>{column.nullable ? 'Nullable' : 'Required'}</span>
                                                {isPrimary && <KeyBadge label="Primary key" />}
                                                {isUnique && <KeyBadge label="Unique" />}
                                                {foreignKey && (
                                                  <span className="ml-2 text-blue-700">
                                                    → {foreignKey.referred_table}.
                                                    {foreignKey.referred_columns.join(', ')}
                                                  </span>
                                                )}
                                              </td>
                                            </tr>
                                          )
                                        })}
                                      </tbody>
                                    </table>
                                  </div>
                                )}
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    ))}
                  </div>
                )
              ) : null}
            </section>
          )}

      <ConfirmDialog
        open={Boolean(deletingConnection)}
        title="Delete database connection?"
        description={`"${deletingConnection?.name ?? ''}" and its stored connection metadata will be permanently removed. Related query history and saved queries may also be deleted.`}
        confirmLabel="Delete connection"
        destructive
        busy={deleteBusy}
        onCancel={() => setDeletingConnection(null)}
        onConfirm={() => void confirmRemoveConnection()}
      />
    </div>
  )
}

const inputClass =
  'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100'

const primaryButtonClass =
  'inline-flex items-center justify-center gap-2 rounded-lg bg-blue-700 px-4 py-2 text-sm font-medium text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50'

const secondaryButtonClass =
  'inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50'

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="block text-xs font-medium text-slate-700">{label}</span>
      {children}
    </label>
  )
}

function ConnectionStatus({
  status,
}: {
  status: Connection['connection_status']
}) {
  if (status === null) {
    return (
      <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
        Not tested
      </span>
    )
  }
  return status === 'connected' ? (
    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">
      <Check size={13} />
      Connected
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-full bg-rose-50 px-2.5 py-1 text-xs font-medium text-rose-700">
      <X size={13} />
      Unavailable
    </span>
  )
}

function KeyBadge({ label }: { label: string }) {
  return (
    <span className="ml-2 inline-flex items-center gap-1 rounded bg-amber-50 px-1.5 py-0.5 font-medium text-amber-800">
      <KeyRound size={11} />
      {label}
    </span>
  )
}

function LoadingState({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center gap-2 p-8 text-sm text-slate-500">
      <LoaderCircle className="animate-spin" size={17} />
      {label}
    </div>
  )
}
