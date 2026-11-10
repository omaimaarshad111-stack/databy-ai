import { createContext } from 'react'
import type { UserProfile } from '../api/client'

export interface AuthContextValue {
  user: UserProfile | null
  loading: boolean
  signIn(email: string, password: string): Promise<void>
  signUp(username: string, email: string, password: string): Promise<void>
  signOut(): void
}

export const AuthContext = createContext<AuthContextValue | null>(null)
