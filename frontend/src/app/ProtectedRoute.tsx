import { LoaderCircle } from 'lucide-react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from './useAuth'

export function ProtectedRoute() {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-3 text-sm text-slate-500">
        <LoaderCircle size={18} className="animate-spin" />
        Restoring your session…
      </div>
    )
  }
  return user ? <Outlet /> : <Navigate to="/login" replace state={{ from: location }} />
}
