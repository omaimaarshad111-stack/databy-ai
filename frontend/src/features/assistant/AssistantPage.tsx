import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  Clock3,
  Database,
  LoaderCircle,
  MessageSquarePlus,
  Play,
  ShieldCheck,
  Sparkles,
  StopCircle,
} from 'lucide-react'
import { useLocation } from 'react-router-dom'
import {
  ApiError,
  createConversation,
  getConversation,
  listConnections,
  listConversations,
  sendAssistantMessage,
  type AssistantCompletion,
  type AssistantProgress,
  type Connection,
  type ConversationMessage,
  type ConversationSummary,
} from '../../api/client'
import { LazyExecutionInsights } from '../../components/charts/LazyExecutionInsights'

function messageFor(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return 'The request could not be completed.'
}

export function AssistantPage() {
  const location = useLocation()
  const initialConversationId = useRef(
    (location.state as { conversationId?: string } | null)?.conversationId ?? '',
  )
  const [connections, setConnections] = useState<Connection[]>([])
  const [connectionId, setConnectionId] = useState('')
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [conversationId, setConversationId] = useState('')
  const [messages, setMessages] = useState<ConversationMessage[]>([])
  const [prompt, setPrompt] = useState('')
  const [progress, setProgress] = useState<AssistantProgress[]>([])
  const [completion, setCompletion] = useState<AssistantCompletion | null>(null)
  const [busy, setBusy] = useState(false)
  const [loadingConversation, setLoadingConversation] = useState(false)
  const [error, setError] = useState('')
  const conversationRequest = useRef(0)
  const activeRequest = useRef<AbortController | null>(null)

  useEffect(() => {
    void loadWorkspace()
    return () => activeRequest.current?.abort()
  }, [])

  useEffect(() => {
    const conversationId = initialConversationId.current
    if (!conversationId) return
    initialConversationId.current = ''
    void openConversation(conversationId)
  }, [])

  const selectedConnection = useMemo(
    () => connections.find((connection) => connection.id === connectionId),
    [connections, connectionId],
  )

  async function loadWorkspace() {
    setError('')
    setBusy(true)
    try {
      const [availableConnections, availableConversations] = await Promise.all([
        listConnections(),
        listConversations(),
      ])
      setConnections(availableConnections)
      setConnectionId((current) =>
        availableConnections.some((connection) => connection.id === current)
          ? current
          : (availableConnections[0]?.id ?? ''),
      )
      setConversations(availableConversations)
    } catch (requestError) {
      setError(messageFor(requestError))
    } finally {
      setBusy(false)
    }
  }

  async function openConversation(id: string) {
    const requestId = ++conversationRequest.current
    setConversationId(id)
    setMessages([])
    setCompletion(null)
    setProgress([])
    if (!id) {
      return
    }
    setLoadingConversation(true)
    setError('')
    try {
      const conversation = await getConversation(id)
      if (requestId === conversationRequest.current) setMessages(conversation.messages)
    } catch (requestError) {
      if (requestId === conversationRequest.current) setError(messageFor(requestError))
    } finally {
      if (requestId === conversationRequest.current) setLoadingConversation(false)
    }
  }

  async function startConversation() {
    setError('')
    try {
      const conversation = await createConversation()
      setConversations((current) => [conversation, ...current])
      setConversationId(conversation.id)
      setMessages([])
      setCompletion(null)
      setProgress([])
    } catch (requestError) {
      setError(messageFor(requestError))
    }
  }

  async function submitPrompt(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const content = prompt.trim()
    if (!connectionId || content.length < 3 || busy) return

    setBusy(true)
    setError('')
    setPrompt('')
    setCompletion(null)
    setProgress([])
    try {
      let activeConversationId = conversationId
      if (!activeConversationId) {
        const created = await createConversation(content.slice(0, 80))
        activeConversationId = created.id
        setConversationId(created.id)
        setConversations((current) => [created, ...current])
      }
      const userMessage: ConversationMessage = {
        id: `pending-${Date.now()}`,
        role: 'user',
        content,
        created_at: new Date().toISOString(),
      }
      setMessages((current) => [...current, userMessage])
      const controller = new AbortController()
      activeRequest.current = controller
      const result = await sendAssistantMessage(
        activeConversationId,
        connectionId,
        content,
        (step) => setProgress((current) => [...current, step]),
        controller.signal,
      )
      setCompletion(result)
      setMessages((current) => [
        ...current.filter((message) => !message.id.startsWith('pending-')),
        result.message,
      ])
      setConversations((current) =>
        current.map((conversation) =>
          conversation.id === result.conversation_id
            ? { ...conversation, title: content.slice(0, 80), updated_at: new Date().toISOString() }
            : conversation,
        ),
      )
    } catch (requestError) {
      if (!(requestError instanceof DOMException && requestError.name === 'AbortError')) {
        setError(messageFor(requestError))
      }
    } finally {
      activeRequest.current = null
      setBusy(false)
    }
  }

  function cancelRequest() {
    activeRequest.current?.abort()
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="mb-2 flex items-center gap-2 text-sm font-medium text-blue-700">
            <Sparkles size={16} />
            Read-only database assistant
          </p>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-950">AI Assistant</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">
            Ask questions about a connected database. Every generated query is validated on the
            server and executed with read-only safeguards.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void startConversation()}
          disabled={busy}
          className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
        >
          <MessageSquarePlus size={16} />
          New conversation
        </button>
      </header>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <div className="mt-5 grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
            <div>
              <label htmlFor="assistant-connection" className="mb-1.5 block text-sm font-medium text-slate-700">
                Database connection
              </label>
              <select
                id="assistant-connection"
                value={connectionId}
                onChange={(event) => {
                  setConnectionId(event.target.value)
                  setCompletion(null)
                  setProgress([])
                }}
                disabled={busy}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              >
                <option value="">Select a connection</option>
                {connections.map((connection) => (
                  <option key={connection.id} value={connection.id}>
                    {connection.name} · {connection.database_type}
                  </option>
                ))}
              </select>
              {!connections.length && (
                <p className="mt-2 text-sm text-slate-500">Add a connection in Database Connections first.</p>
              )}
            </div>
            <div>
              <label htmlFor="assistant-conversation" className="mb-1.5 block text-sm font-medium text-slate-700">
                Conversation
              </label>
              <select
                id="assistant-conversation"
                value={conversationId}
                onChange={(event) => void openConversation(event.target.value)}
                disabled={busy || loadingConversation}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              >
                <option value="">Start a new conversation</option>
                {conversations.map((conversation) => (
                  <option key={conversation.id} value={conversation.id}>{conversation.title}</option>
                ))}
              </select>
            </div>
        </div>
      </section>

      {error && (
        <div role="alert" className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          <AlertCircle size={18} className="mt-0.5 shrink-0" />
          {error}
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(320px,0.8fr)]">
          <section className="flex min-h-[560px] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
              <div>
                <h2 className="font-semibold text-slate-900">Conversation</h2>
                <p className="mt-0.5 text-xs text-slate-500">
                  {selectedConnection ? selectedConnection.name : 'Choose a connected database'}
                </p>
              </div>
              <Database size={18} className="text-slate-400" />
            </div>
            <div className="flex-1 space-y-4 overflow-y-auto p-5">
              {loadingConversation && <p className="text-sm text-slate-500">Loading conversation…</p>}
              {!messages.length && !loadingConversation && (
                <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-6 text-center">
                  <Sparkles size={22} className="mx-auto text-blue-500" />
                  <p className="mt-3 font-medium text-slate-800">What would you like to learn?</p>
                  <p className="mt-1 text-sm text-slate-500">Try asking for a summary, ranking, or filtered result.</p>
                </div>
              )}
              {messages.map((message) => (
                <div
                  key={message.id}
                  className={`max-w-[92%] rounded-2xl px-4 py-3 text-sm leading-6 ${
                    message.role === 'user'
                      ? 'ml-auto bg-blue-600 text-white'
                      : 'bg-slate-100 text-slate-800'
                  }`}
                >
                  <p className="whitespace-pre-wrap">{message.content}</p>
                </div>
              ))}
              {busy && (
                <div className="flex items-center gap-2 text-sm text-blue-700">
                  <LoaderCircle size={16} className="animate-spin" />
                  Working through the request…
                </div>
              )}
            </div>
            <form onSubmit={(event) => void submitPrompt(event)} className="border-t border-slate-100 p-4">
              <label className="sr-only" htmlFor="assistant-prompt">Ask a database question</label>
              <textarea
                id="assistant-prompt"
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="Ask a question about your data…"
                rows={3}
                maxLength={4000}
                disabled={busy || !connectionId}
                className="w-full resize-y rounded-xl border border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50"
              />
              <div className="mt-2 flex items-center justify-between gap-3">
                <p className="text-xs text-slate-500">Read-only queries only. Results are bounded.</p>
                <div className="flex gap-2">
                  {busy && (
                    <button type="button" onClick={cancelRequest} className="button-secondary">
                      <StopCircle size={15} />Stop
                    </button>
                  )}
                  <button
                    type="submit"
                    disabled={busy || !connectionId || prompt.trim().length < 3}
                    className="button-primary"
                  >
                    {busy ? <LoaderCircle size={15} className="animate-spin" /> : <Play size={15} />}
                    {busy ? 'Running' : 'Ask'}
                  </button>
                </div>
              </div>
            </form>
          </section>

          <aside className="space-y-6">
            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-center gap-2">
                <Clock3 size={17} className="text-blue-600" />
                <h2 className="font-semibold text-slate-900">Execution steps</h2>
              </div>
              {progress.length === 0 ? (
                <p className="mt-4 text-sm text-slate-500">The assistant will show safe progress updates here.</p>
              ) : (
                <ol className="mt-4 space-y-3">
                  {progress.map((step, index) => (
                    <li key={`${step.name}-${index}`} className="flex gap-3 text-sm">
                      {step.status === 'completed'
                        ? <CheckCircle2 size={17} className="mt-0.5 shrink-0 text-emerald-600" />
                        : step.status === 'failed'
                          ? <AlertCircle size={17} className="mt-0.5 shrink-0 text-rose-600" />
                          : <LoaderCircle size={17} className="mt-0.5 shrink-0 animate-spin text-blue-600" />}
                      <div>
                        <p className="font-medium capitalize text-slate-800">{step.name.replaceAll('_', ' ')}</p>
                        <p className="mt-0.5 text-xs leading-5 text-slate-500">{step.message}</p>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </section>

            {completion && (
              <>
                <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                  <div className="flex items-center justify-between">
                    <h2 className="font-semibold text-slate-900">SQL and validation</h2>
                    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium ${
                      completion.validation_status === 'valid'
                        ? 'bg-emerald-50 text-emerald-700'
                        : completion.validation_status === 'invalid'
                          ? 'bg-red-50 text-red-700'
                          : 'bg-slate-100 text-slate-600'
                    }`}>
                      <ShieldCheck size={13} />
                      {completion.validation_status === 'valid' ? 'Validated' : completion.validation_status === 'invalid' ? 'Rejected' : 'Not run'}
                    </span>
                  </div>
                  {completion.generated_sql ? (
                    <pre className="mt-4 overflow-x-auto rounded-xl bg-slate-950 p-4 text-xs leading-5 text-blue-100">
                      <code>{completion.generated_sql}</code>
                    </pre>
                  ) : (
                    <p className="mt-3 text-sm text-slate-500">No SQL was generated for this request.</p>
                  )}
                  {completion.validation_errors.length > 0 && (
                    <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-red-700">
                      {completion.validation_errors.map((validationError) => <li key={validationError}>{validationError}</li>)}
                    </ul>
                  )}
                </section>

                {completion.execution && (
                  <LazyExecutionInsights result={completion.execution} />
                )}
              </>
            )}
          </aside>
        </div>
    </div>
  )
}
