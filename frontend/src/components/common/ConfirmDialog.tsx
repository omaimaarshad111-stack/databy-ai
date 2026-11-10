import { AlertTriangle, LoaderCircle, X } from 'lucide-react'

interface ConfirmDialogProps {
  open: boolean
  title: string
  description: string
  confirmLabel?: string
  busy?: boolean
  destructive?: boolean
  onCancel(): void
  onConfirm(): void
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = 'Confirm',
  busy = false,
  destructive = false,
  onCancel,
  onConfirm,
}: ConfirmDialogProps) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !busy) onCancel()
    }}>
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby="confirm-description"
        className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-5 shadow-xl"
      >
        <div className="flex items-start gap-3">
          <div className={`rounded-lg p-2 ${destructive ? 'bg-rose-50 text-rose-700' : 'bg-amber-50 text-amber-700'}`}>
            <AlertTriangle size={18} />
          </div>
          <div className="min-w-0 flex-1">
            <h2 id="confirm-title" className="font-semibold text-slate-900">{title}</h2>
            <p id="confirm-description" className="mt-2 text-sm leading-6 text-slate-600">{description}</p>
          </div>
          <button type="button" onClick={onCancel} disabled={busy} aria-label="Close dialog" className="rounded-md p-1 text-slate-400 hover:bg-slate-100 disabled:opacity-50">
            <X size={18} />
          </button>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <button type="button" onClick={onCancel} disabled={busy} className="button-secondary">Cancel</button>
          <button type="button" onClick={onConfirm} disabled={busy} className={destructive ? 'button-danger' : 'button-primary'}>
            {busy && <LoaderCircle size={15} className="animate-spin" />}
            {busy ? 'Working…' : confirmLabel}
          </button>
        </div>
      </section>
    </div>
  )
}
