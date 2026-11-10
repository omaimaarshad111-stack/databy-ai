import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import {
  getCurrentUser,
  login as loginRequest,
  registerAccount,
  setAccessToken,
  type UserProfile,
} from '../api/client'
import { AuthContext } from './auth-context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null)
  const [loading, setLoading] = useState(() =>
    Boolean(sessionStorage.getItem('databy.accessToken')),
  )

  const signOut = useCallback(() => {
    setAccessToken(null)
    setUser(null)
  }, [])

  const signIn = useCallback(async (email: string, password: string) => {
    const token = await loginRequest(email, password)
    setAccessToken(token.access_token)
    try {
      setUser(await getCurrentUser())
    } catch (error) {
      setAccessToken(null)
      throw error
    }
  }, [])

  const signUp = useCallback(async (username: string, email: string, password: string) => {
    await registerAccount(username, email, password)
    await signIn(email, password)
  }, [signIn])

  useEffect(() => {
    let active = true
    const expire = () => {
      if (active) setUser(null)
    }
    window.addEventListener('databy-auth-expired', expire)
    const token = sessionStorage.getItem('databy.accessToken')
    if (token) {
      void getCurrentUser()
        .then((profile) => {
          if (active) setUser(profile)
        })
        .catch(() => {
          if (active) signOut()
        })
        .finally(() => {
          if (active) setLoading(false)
        })
    }
    return () => {
      active = false
      window.removeEventListener('databy-auth-expired', expire)
    }
  }, [signOut])

  const value = useMemo(
    () => ({ user, loading, signIn, signUp, signOut }),
    [user, loading, signIn, signUp, signOut],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
