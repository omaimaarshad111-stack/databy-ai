import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { getCurrentUser, login, registerAccount, setAccessToken } from '../../api/client'
import { AuthProvider } from '../../app/AuthContext'
import { ProtectedRoute } from '../../app/ProtectedRoute'
import { AuthPage } from './AuthPage'

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return {
    ...actual,
    getCurrentUser: vi.fn(),
    login: vi.fn(),
    registerAccount: vi.fn(),
  }
})

const profile = {
  id: 'user-1',
  username: 'data-user',
  email: 'data@example.com',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

function renderAuth(initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<AuthPage mode="login" />} />
          <Route path="/register" element={<AuthPage mode="register" />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/" element={<p>Workspace is protected</p>} />
            <Route path="/private" element={<p>Private destination</p>} />
          </Route>
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

afterEach(() => {
  setAccessToken(null)
  vi.clearAllMocks()
})

describe('authentication routes', () => {
  it('signs in and returns to the originally requested route', async () => {
    vi.mocked(login).mockResolvedValue({ access_token: 'session-token', token_type: 'bearer' })
    vi.mocked(getCurrentUser).mockResolvedValue(profile)
    renderAuth('/private')

    await screen.findByRole('heading', { name: 'Sign in' })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'data@example.com' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password-123' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText('Private destination')).toBeInTheDocument()
    expect(login).toHaveBeenCalledWith('data@example.com', 'password-123')
    expect(sessionStorage.getItem('databy.accessToken')).toBe('session-token')
  })

  it('registers then authenticates a new account', async () => {
    vi.mocked(registerAccount).mockResolvedValue(profile)
    vi.mocked(login).mockResolvedValue({ access_token: 'new-session', token_type: 'bearer' })
    vi.mocked(getCurrentUser).mockResolvedValue(profile)
    renderAuth('/register')

    await screen.findByRole('heading', { name: 'Get started' })
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'data-user' } })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'data@example.com' } })
    fireEvent.change(screen.getByLabelText(/Password/), { target: { value: 'long-password-123' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }))

    await waitFor(() => expect(registerAccount).toHaveBeenCalledWith('data-user', 'data@example.com', 'long-password-123'))
    expect(await screen.findByText('Workspace is protected')).toBeInTheDocument()
    expect(login).toHaveBeenCalledWith('data@example.com', 'long-password-123')
  })
})
