import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { LoaderCircle } from 'lucide-react'
import { AuthProvider } from './AuthContext'
import { ProtectedRoute } from './ProtectedRoute'
import { RouteErrorBoundary } from './RouteErrorBoundary'
import { AppLayout } from '../components/layout/AppLayout'
import { AuthPage } from '../features/auth/AuthPage'

const DashboardPage = lazy(() => import('../features/dashboard/DashboardPage').then((module) => ({ default: module.DashboardPage })))
const ConnectionsPage = lazy(() => import('../features/explorer/ConnectionsPage').then((module) => ({ default: module.ConnectionsPage })))
const AssistantPage = lazy(() => import('../features/assistant/AssistantPage').then((module) => ({ default: module.AssistantPage })))
const SQLRunnerPage = lazy(() => import('../features/assistant/SQLRunnerPage').then((module) => ({ default: module.SQLRunnerPage })))
const HistoryPage = lazy(() => import('../features/history/HistoryPage').then((module) => ({ default: module.HistoryPage })))
const AnalyticsPage = lazy(() => import('../features/analytics/AnalyticsPage').then((module) => ({ default: module.AnalyticsPage })))
const SavedQueriesPage = lazy(() => import('../features/saved-queries/SavedQueriesPage').then((module) => ({ default: module.SavedQueriesPage })))
const SettingsPage = lazy(() => import('../features/settings/SettingsPage').then((module) => ({ default: module.SettingsPage })))

function PageLoading() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center gap-2 text-sm text-slate-500">
      <LoaderCircle size={17} className="animate-spin" />Loading workspace…
    </div>
  )
}

export default function App() {
  return (
    <RouteErrorBoundary>
      <BrowserRouter>
        <AuthProvider>
          <Suspense fallback={<PageLoading />}>
            <Routes>
              <Route path="/login" element={<AuthPage mode="login" />} />
              <Route path="/register" element={<AuthPage mode="register" />} />
              <Route element={<ProtectedRoute />}>
                <Route element={<AppLayout />}>
                  <Route path="/" element={<DashboardPage />} />
                  <Route path="/assistant" element={<AssistantPage />} />
                  <Route path="/explorer" element={<ConnectionsPage />} />
                  <Route path="/sql-runner" element={<SQLRunnerPage />} />
                  <Route path="/connections" element={<Navigate to="/explorer" replace />} />
                  <Route path="/history" element={<HistoryPage />} />
                  <Route path="/analytics" element={<AnalyticsPage />} />
                  <Route path="/saved-queries" element={<SavedQueriesPage />} />
                  <Route path="/settings" element={<SettingsPage />} />
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Route>
              </Route>
            </Routes>
          </Suspense>
        </AuthProvider>
      </BrowserRouter>
    </RouteErrorBoundary>
  )
}
