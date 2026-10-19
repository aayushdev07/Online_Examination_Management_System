import { AlertTriangle, CheckCircle2, Info, Loader2, X } from 'lucide-react'
import {
  createContext, useCallback, useContext, useEffect, useRef, useState,
  type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react'
import type { ApiError } from '../lib/api'
import { cx } from '../lib/format'

// --------------------------------------------------------------------------- buttons
type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'
const variants: Record<Variant, string> = {
  primary: 'bg-ink text-white hover:bg-ink-soft disabled:bg-ink/50',
  secondary: 'bg-surface text-ink border border-rule hover:border-ink/40 disabled:text-muted',
  danger: 'bg-danger text-white hover:bg-danger/90 disabled:bg-danger/50',
  ghost: 'text-ink hover:bg-ink/5 disabled:text-muted',
}

export function Button({ variant = 'primary', busy, className, children, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  return (
    <button
      type="button"
      {...rest}
      disabled={rest.disabled || busy}
      className={cx('inline-flex items-center justify-center gap-2 rounded-md px-3.5 py-2 text-sm font-semibold',
        'transition-colors disabled:cursor-not-allowed', variants[variant], className)}
    >
      {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  )
}

// --------------------------------------------------------------------------- layout blocks
export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  )
}

export function Panel({ title, actions, children, className, flush }:
  { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; flush?: boolean }) {
  return (
    <section className={cx('min-w-0 rounded-lg border border-rule bg-surface', className)}>
      {(title || actions) && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-rule px-4 py-3">
          {title && <h2 className="font-semibold">{title}</h2>}
          {actions}
        </div>
      )}
      <div className={flush ? '' : 'p-4'}>{children}</div>
    </section>
  )
}

export function Stat({ label, value, hint, tone = 'ink' }:
  { label: string; value: ReactNode; hint?: ReactNode; tone?: 'ink' | 'teal' | 'amber' | 'danger' }) {
  const color = { ink: 'text-ink', teal: 'text-teal', amber: 'text-amber', danger: 'text-danger' }[tone]
  return (
    <div className="rounded-lg border border-rule bg-surface px-4 py-3">
      <div className="text-sm text-muted">{label}</div>
      <div className={cx('mt-1 text-2xl font-bold tabular-nums', color)}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted">{hint}</div>}
    </div>
  )
}

// --------------------------------------------------------------------------- badges
const badgeTones: Record<string, string> = {
  ACTIVE: 'bg-teal-soft text-teal', PASS: 'bg-teal-soft text-teal', EVALUATED: 'bg-teal-soft text-teal',
  SUCCESS: 'bg-teal-soft text-teal', success: 'bg-teal-soft text-teal', up: 'bg-teal-soft text-teal',
  SCHEDULED: 'bg-ink/8 text-ink', IN_PROGRESS: 'bg-bubble-soft text-amber', SUBMITTED: 'bg-amber-soft text-amber',
  COMPLETED: 'bg-ink/8 text-ink-soft', CANCELLED: 'bg-danger-soft text-danger', FAIL: 'bg-danger-soft text-danger',
  ERROR: 'bg-danger-soft text-danger', error: 'bg-danger-soft text-danger', down: 'bg-danger-soft text-danger',
  REJECTED: 'bg-amber-soft text-amber', expected_error: 'bg-amber-soft text-amber',
  ADMIN: 'bg-ink text-white', FACULTY: 'bg-ink/8 text-ink', STUDENT: 'bg-bubble-soft text-ink',
}

export function Badge({ children, tone }: { children: ReactNode; tone?: string }) {
  const key = tone ?? (typeof children === 'string' ? children : '')
  return (
    <span className={cx('inline-flex items-center rounded px-2 py-0.5 text-xs font-semibold whitespace-nowrap',
      badgeTones[key] ?? 'bg-ink/8 text-ink-soft')}>
      {typeof children === 'string' ? children.replaceAll('_', ' ').toLowerCase() : children}
    </span>
  )
}

// --------------------------------------------------------------------------- feedback
export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 py-8 text-muted">
      <Loader2 className="size-5 animate-spin" aria-hidden /> {label}…
    </div>
  )
}

export function ErrorBanner({ error, onRetry }: { error: ApiError | null | undefined; onRetry?: () => void }) {
  if (!error) return null
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border border-danger/30 bg-danger-soft px-4 py-3 text-sm">
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden />
      <div className="flex-1">
        <p className="font-semibold text-danger">{error.message}</p>
        <p className="mt-0.5 text-xs text-muted">
          {error.status ? `HTTP ${error.status}` : 'No response'} · {error.code}
          {(error.details as { mysql_errno?: number } | undefined)?.mysql_errno
            ? ` · MySQL error ${(error.details as { mysql_errno: number }).mysql_errno}` : ''}
          {error.requestId ? ` · request ${error.requestId.slice(0, 8)}` : ''}
        </p>
      </div>
      {onRetry && <Button variant="secondary" onClick={onRetry}>Retry</Button>}
    </div>
  )
}

export function Callout({ tone = 'info', children }: { tone?: 'info' | 'success' | 'warning'; children: ReactNode }) {
  const styles = {
    info: 'border-ink/15 bg-ink/[0.03]',
    success: 'border-teal/30 bg-teal-soft',
    warning: 'border-amber/30 bg-amber-soft',
  }[tone]
  const Icon = tone === 'success' ? CheckCircle2 : tone === 'warning' ? AlertTriangle : Info
  return (
    <div className={cx('flex gap-3 rounded-lg border px-4 py-3 text-sm', styles)}>
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="flex-1">{children}</div>
    </div>
  )
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-rule px-6 py-10 text-center">
      <p className="font-semibold">{title}</p>
      {children && <div className="mt-1 text-sm text-muted">{children}</div>}
    </div>
  )
}

// --------------------------------------------------------------------------- forms
export function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium">{label}</span>
      {children}
      {hint && !error && <span className="mt-1 block text-xs text-muted">{hint}</span>}
      {error && <span className="mt-1 block text-xs font-medium text-danger">{error}</span>}
    </label>
  )
}

const control = 'w-full rounded-md border border-rule bg-surface px-3 py-2 text-sm text-ink placeholder:text-muted/70 ' +
  'focus:border-teal focus:outline-none focus:ring-2 focus:ring-teal/20 disabled:bg-paper'

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(control, props.className)} />
}
export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx(control, props.className)} />
}
export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(control, props.className)} />
}

// --------------------------------------------------------------------------- modal
export function Modal({ open, title, onClose, children, footer, wide }:
  { open: boolean; title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    ref.current?.focus()
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/40 p-4 sm:p-10"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title}
        className={cx('w-full rounded-lg bg-surface shadow-xl', wide ? 'max-w-3xl' : 'max-w-lg')}>
        <div className="flex items-center justify-between border-b border-rule px-5 py-3">
          <h2 className="font-semibold">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded p-1 hover:bg-ink/5">
            <X className="size-4" />
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-rule px-5 py-3">{footer}</div>}
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------- toasts
interface Toast { id: number; tone: 'success' | 'error'; text: string }
const ToastContext = createContext<(tone: Toast['tone'], text: string) => void>(() => undefined)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const push = useCallback((tone: Toast['tone'], text: string) => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t, { id, tone, text }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500)
  }, [])
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div aria-live="polite" className="fixed right-4 bottom-4 z-[60] flex w-80 flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} className={cx('rounded-md px-4 py-3 text-sm font-medium shadow-lg',
            t.tone === 'success' ? 'bg-ink text-white' : 'bg-danger text-white')}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export const useToast = () => useContext(ToastContext)

// --------------------------------------------------------------------------- pagination
export function Pagination({ page, pageSize, total, onPage }:
  { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  return (
    <div className="flex items-center justify-between gap-3 px-4 py-3 text-sm text-muted">
      <span>{total.toLocaleString()} rows · page {page} of {pages}</span>
      <div className="flex gap-2">
        <Button variant="secondary" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</Button>
        <Button variant="secondary" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</Button>
      </div>
    </div>
  )
}
