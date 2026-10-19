import { useState, type FormEvent } from 'react'
import { Button, ErrorBanner, Field, Input } from '../components/ui'
import { ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cx } from '../lib/format'

const DEMO = [
  { label: 'Student', username: 'aarav.shah', type: 'STUDENT' as const },
  { label: 'Faculty', username: 'rdeshpande', type: 'STAFF' as const },
  { label: 'Administrator', username: 'admin', type: 'STAFF' as const },
]

/** A strip of answer-sheet bubbles: the visual signature of the app. */
function BubbleSheet() {
  const rows = ['A', 'B', 'C', 'D']
  const filled = [1, 3, 0, 2, 2, 1, 3, 0]
  return (
    <div className="grid w-fit grid-cols-[auto_repeat(8,1fr)] gap-x-3 gap-y-2.5" aria-hidden>
      <span />
      {filled.map((_, q) => <span key={q} className="text-center text-xs text-white/40">{q + 1}</span>)}
      {rows.map((r, ri) => (
        <div key={r} className="contents">
          <span className="text-xs text-white/40">{r}</span>
          {filled.map((f, q) => (
            <span key={q} className={cx('size-5 rounded-full border-[1.5px]',
              f === ri ? 'border-bubble bg-bubble' : 'border-white/30')} />
          ))}
        </div>
      ))}
    </div>
  )
}

export default function Login() {
  const { login, register } = useAuth()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [accountType, setAccountType] = useState<'STUDENT' | 'STAFF'>('STUDENT')
  const [form, setForm] = useState({ username: '', password: '', student_name: '', email: '' })
  const [error, setError] = useState<ApiError | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value })

  function validate(): boolean {
    const errs: Record<string, string> = {}
    if (!form.username.trim()) errs.username = 'Enter your username'
    if (!form.password) errs.password = 'Enter your password'
    if (mode === 'register') {
      if (!form.student_name.trim()) errs.student_name = 'Enter your full name'
      if (!/^\S+@\S+\.\S+$/.test(form.email)) errs.email = 'Enter a valid e-mail address'
      if (!/^[A-Za-z0-9_.]{3,50}$/.test(form.username)) errs.username = '3-50 letters, digits, "." or "_"'
      if (form.password.length < 8 || !/[A-Za-z]/.test(form.password) || !/\d/.test(form.password))
        errs.password = 'At least 8 characters with a letter and a digit'
    }
    setFieldErrors(errs)
    return Object.keys(errs).length === 0
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!validate()) return
    setBusy(true)
    setError(null)
    try {
      if (mode === 'login') await login(form.username.trim(), form.password, accountType)
      else await register({ student_name: form.student_name.trim(), email: form.email.trim(),
                            username: form.username.trim(), password: form.password })
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, 'error', String(err)))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <section className="flex flex-col justify-between bg-ink px-8 py-10 text-white sm:px-14">
        <div className="text-sm font-semibold tracking-wide text-white/70">OEMS</div>
        <div className="my-12 max-w-lg">
          <BubbleSheet />
          <h1 className="mt-10 text-4xl leading-tight font-bold tracking-tight sm:text-5xl">
            Online examinations, backed by a database you can watch.
          </h1>
          <p className="mt-4 max-w-md text-lg text-white/70">
            Students take exams, faculty grade them, and every insert, trigger and transaction behind it runs on
            real MySQL in the DBMS lab.
          </p>
        </div>
        <p className="text-sm text-white/50">React · FastAPI · MySQL 8 (InnoDB)</p>
      </section>

      <section className="flex items-center justify-center px-6 py-10">
        <form onSubmit={submit} noValidate className="w-full max-w-sm space-y-5">
          <div>
            <h2 className="text-2xl font-bold">{mode === 'login' ? 'Sign in' : 'Create a student account'}</h2>
            <p className="mt-1 text-sm text-muted">
              {mode === 'login' ? 'New student? ' : 'Already registered? '}
              <button type="button" className="font-semibold text-teal underline-offset-2 hover:underline"
                onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(null); setFieldErrors({}) }}>
                {mode === 'login' ? 'Create an account' : 'Sign in instead'}
              </button>
            </p>
          </div>

          {mode === 'login' && (
            <div role="radiogroup" aria-label="Account type" className="grid grid-cols-2 rounded-md border border-rule p-1">
              {(['STUDENT', 'STAFF'] as const).map((t) => (
                <button key={t} type="button" role="radio" aria-checked={accountType === t} onClick={() => setAccountType(t)}
                  className={cx('rounded px-3 py-1.5 text-sm font-semibold',
                    accountType === t ? 'bg-ink text-white' : 'text-muted hover:text-ink')}>
                  {t === 'STUDENT' ? 'Student' : 'Faculty / admin'}
                </button>
              ))}
            </div>
          )}

          {mode === 'register' && (
            <>
              <Field label="Full name" error={fieldErrors.student_name}>
                <Input value={form.student_name} onChange={set('student_name')} autoComplete="name" />
              </Field>
              <Field label="E-mail" error={fieldErrors.email}>
                <Input type="email" value={form.email} onChange={set('email')} autoComplete="email" />
              </Field>
            </>
          )}
          <Field label={mode === 'login' ? 'Username or e-mail' : 'Username'} error={fieldErrors.username}>
            <Input value={form.username} onChange={set('username')} autoComplete="username" />
          </Field>
          <Field label="Password" error={fieldErrors.password}
            hint={mode === 'register' ? 'At least 8 characters, with a letter and a digit' : undefined}>
            <Input type="password" value={form.password} onChange={set('password')}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'} />
          </Field>

          <ErrorBanner error={error} />
          <Button type="submit" busy={busy} className="w-full py-2.5">
            {mode === 'login' ? 'Sign in' : 'Create account'}
          </Button>

          {mode === 'login' && (
            <div className="rounded-md border border-rule bg-surface p-3 text-sm">
              <p className="font-semibold">Demo accounts</p>
              <p className="text-xs text-muted">Password for all: Password@123</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {DEMO.map((d) => (
                  <button key={d.username} type="button"
                    className="rounded border border-rule px-2 py-1 text-xs hover:border-ink/40"
                    onClick={() => { setAccountType(d.type); setForm({ ...form, username: d.username, password: 'Password@123' }) }}>
                    {d.label}: {d.username}
                  </button>
                ))}
              </div>
            </div>
          )}
        </form>
      </section>
    </div>
  )
}
