import { Component, type ReactNode } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'

interface BoundaryState {
  hasError: boolean
}

export class RouteErrorBoundary extends Component<{ children: ReactNode }, BoundaryState> {
  state: BoundaryState = { hasError: false }

  static getDerivedStateFromError(): BoundaryState {
    return { hasError: true }
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="flex min-h-screen items-center justify-center bg-slate-50 p-4">
          <section role="alert" className="max-w-md rounded-2xl border border-slate-200 bg-white p-6 text-center shadow-sm">
            <AlertTriangle className="mx-auto text-amber-600" size={24} />
            <h1 className="mt-3 text-lg font-semibold text-slate-900">This page could not be displayed</h1>
            <p className="mt-2 text-sm leading-6 text-slate-500">The rest of the application remains available. Reload the page to try again.</p>
            <button type="button" onClick={() => window.location.reload()} className="button-primary mt-5"><RefreshCw size={15} />Reload page</button>
          </section>
        </main>
      )
    }
    return this.props.children
  }
}
