import { lazy, Suspense } from 'react'
import { LoaderCircle } from 'lucide-react'
import type { SQLExecutionResult } from '../../api/client'

const ExecutionInsights = lazy(() =>
  import('./ExecutionInsights').then((module) => ({ default: module.ExecutionInsights })),
)

export function LazyExecutionInsights({ result }: { result: SQLExecutionResult }) {
  return (
    <Suspense fallback={<div className="flex items-center justify-center gap-2 p-8 text-sm text-slate-500"><LoaderCircle size={16} className="animate-spin" />Loading visualizations…</div>}>
      <ExecutionInsights result={result} />
    </Suspense>
  )
}
