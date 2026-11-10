import { useState, type FormEvent } from 'react'
import { ArrowRight, Database, LoaderCircle, LockKeyhole } from 'lucide-react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { useAuth } from '../../app/useAuth'

interface RedirectState {
  from?: { pathname?: string }
}

export function AuthPage({ mode }: { mode: 'login' | 'register' }) {
  const { user, loading: sessionLoading, signIn, signUp } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const redirect = (location.state as RedirectState | null)?.from?.pathname ?? '/'
  if (sessionLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-2 text-sm text-slate-500">
        <LoaderCircle size={17} className="animate-spin" />Restoring your session…
      </div>
    )
  }
  if (user) return <Navigate to={redirect} replace />

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      if (mode === 'register') await signUp(username.trim(), email.trim(), password)
      else await signIn(email.trim(), password)
      navigate(redirect, { replace: true })
    } catch (requestError) {
      setError(
        requestError instanceof ApiError
          ? requestError.message
          : requestError instanceof Error
            ? requestError.message
            : 'Authentication could not be completed.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-10">
      <section className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
        <div className="mb-7 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600 text-white">
            <Database size={20} />
          </div>
          <div>
            <p className="text-lg font-semibold tracking-tight text-slate-950">databy.ai</p>
            <p className="text-xs text-slate-500">A secure workspace for your data</p>
          </div>
        </div>
        <p className="flex items-center gap-2 text-sm font-medium text-blue-700">
          <LockKeyhole size={15} />
          {mode === 'login' ? 'Welcome back' : 'Create your workspace account'}
        </p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">
          {mode === 'login' ? 'Sign in' : 'Get started'}
        </h1>
        <p className="mt-2 text-sm leading-6 text-slate-500">
          {mode === 'login'
            ? 'Sign in to manage connections and query your databases.'
            : 'Create an account to begin connecting your databases.'}
        </p>

        <form onSubmit={(event) => void submit(event)} className="mt-6 space-y-4">
          {mode === 'register' && (
            <label className="block text-sm font-medium text-slate-700">
              Username
              <input
                required
                minLength={3}
                maxLength={32}
                pattern="[-A-Za-z0-9_.]+"
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                className="form-input mt-1.5"
              />
            </label>
          )}
          <label className="block text-sm font-medium text-slate-700">
            Email
            <input
              required
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="form-input mt-1.5"
            />
          </label>
          <label className="block text-sm font-medium text-slate-700">
            Password
            <input
              required
              type="password"
              minLength={mode === 'register' ? 12 : 1}
              maxLength={128}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="form-input mt-1.5"
            />
            {mode === 'register' && (
              <span className="mt-1 block text-xs font-normal text-slate-500">
                Use at least 12 characters.
              </span>
            )}
          </label>
          {error && <p role="alert" className="status-error">{error}</p>}
          <button type="submit" disabled={busy} className="button-primary w-full">
            {busy ? <LoaderCircle size={16} className="animate-spin" /> : <ArrowRight size={16} />}
            {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-slate-600">
          {mode === 'login' ? 'New to databy.ai?' : 'Already have an account?'}{' '}
          <Link
            to={mode === 'login' ? '/register' : '/login'}
            className="font-medium text-blue-700 hover:text-blue-800"
          >
            {mode === 'login' ? 'Create account' : 'Sign in'}
          </Link>
        </p>
      </section>
    </main>
  )
}
