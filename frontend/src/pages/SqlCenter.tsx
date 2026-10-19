import { ChevronDown, ChevronRight, Eraser, Lock, Play, RefreshCw, ShieldAlert, SquareTerminal, Timer } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { diffRows, ResultGrid, SqlBlock } from '../components/data'
import { Badge, Button, Callout, ErrorBanner, Field, Input, Modal, Spinner, Textarea } from '../components/ui'
import { ApiError, get, post, qs } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cx, fmtMs, fmtNumber } from '../lib/format'
import { useAction, useLoad } from '../lib/hooks'
import type { LabCategory, LabExample, RunResult, StepResult } from '../lib/types'

interface Config {
  main_database: string; lab_database: string; accounts: Record<string, string>; freeform_enabled: boolean
  max_rows: number; timeout_seconds: number; rate_limit_per_minute: number; max_sql_chars: number
}
interface SchemaSummary { database: string; tables: { name: string; type: string; row_count: number | null }[] }

const FREEFORM = '__freeform__'

const STATUS_STYLE: Record<string, { label: string; className: string }> = {
  success: { label: 'OK', className: 'bg-teal-soft text-teal' },
  expected_error: { label: 'rejected as expected', className: 'bg-amber-soft text-amber' },
  error: { label: 'error', className: 'bg-danger-soft text-danger' },
  skipped: { label: 'skipped', className: 'bg-ink/8 text-muted' },
  not_run: { label: 'not run', className: 'bg-ink/8 text-muted' },
  unexpected_success: { label: 'succeeded unexpectedly', className: 'bg-danger-soft text-danger' },
}

const ROLE_LABEL: Record<string, string> = {
  setup: 'setup', before: 'before', main: 'statement', after: 'after', restore: 'restore', info: 'info',
}

export default function SqlCenter() {
  const { user } = useAuth()
  const catalog = useLoad(() => get<{ categories: LabCategory[]; examples: LabExample[] }>('/sql/examples'))
  const config = useLoad(() => get<Config>('/sql/config'))
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [openCats, setOpenCats] = useState<Set<string>>(new Set(['DDL']))
  const [params, setParams] = useState<Record<string, string>>({})
  const [freeSql, setFreeSql] = useState('SELECT exam_id, title, status, duration_minutes\n  FROM exam\n ORDER BY exam_id;')
  const [result, setResult] = useState<RunResult | null>(null)
  const [confirm, setConfirm] = useState<null | { action: 'run' | 'cleanup'; details?: unknown }>(null)
  const [objectsTick, setObjectsTick] = useState(0)

  const examples = useMemo(() => catalog.data?.examples ?? [], [catalog.data])
  const selected = examples.find((e) => e.id === selectedId) ?? null
  const isFree = selectedId === FREEFORM
  const targetDb = isFree ? 'lab' : selected?.target ?? 'lab'
  const objects = useLoad(() => get<SchemaSummary>(`/db/schema${qs({ database: targetDb })}`), [targetDb, objectsTick])

  useEffect(() => {
    if (!selectedId && examples.length) setSelectedId(examples[0].id)
  }, [examples, selectedId])

  useEffect(() => {
    setParams(Object.fromEntries((selected?.params ?? []).map((p) => [p.name, String(p.default ?? '')])))
    setResult(null)
  }, [selected])

  const execute = useAction(async (action: 'run' | 'cleanup', confirmed = false) => {
    const body = isFree
      ? { sql: freeSql, confirm: confirmed }
      : { example_id: selectedId, action, confirm: confirmed, params: selected?.params.length ? params : undefined }
    try {
      const res = await post<RunResult>('/sql/execute', body)
      setResult(res)
      setConfirm(null)
      if (targetDb === 'lab' || isFree) setObjectsTick((t) => t + 1)   // DDL may have changed the schema
    } catch (e) {
      if (e instanceof ApiError && e.code === 'confirmation_required') {
        setConfirm({ action, details: e.details })
        return
      }
      throw e
    }
  })

  function run(action: 'run' | 'cleanup') {
    if (!isFree && action === 'run' && selected?.destructive) setConfirm({ action })
    else void execute.run(action, false)
  }

  const byCategory = useMemo(() => {
    const map = new Map<string, LabExample[]>()
    for (const e of examples) map.set(e.category, [...(map.get(e.category) ?? []), e])
    return map
  }, [examples])

  if (catalog.loading && !catalog.data) return <Spinner label="Loading SQL catalog" />
  const cfg = config.data
  const dbName = targetDb === 'main' ? cfg?.main_database : cfg?.lab_database
  const account = isFree ? cfg?.accounts.lab : selected ? cfg?.accounts[selected.account] : ''

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">SQL Command Center</h1>
          <p className="text-muted">Pick an example, run it against MySQL and inspect the real result.</p>
        </div>
        {cfg && (
          <div className="flex items-center gap-2 rounded-md border border-rule bg-surface px-3 py-2 text-sm" aria-live="polite">
            <span className={cx('size-2.5 rounded-full', targetDb === 'main' ? 'bg-teal' : 'bg-bubble ring-1 ring-amber')} aria-hidden />
            <span className="font-mono font-semibold">{dbName}</span>
            <span className="text-muted">as</span>
            <span className="font-mono">{account}</span>
            <Badge tone={targetDb === 'main' ? 'PASS' : 'SUBMITTED'}>{targetDb === 'main' ? 'read-only' : 'disposable lab'}</Badge>
          </div>
        )}
      </header>
      <ErrorBanner error={catalog.error ?? config.error} onRetry={catalog.reload} />

      <div className="grid gap-4 xl:grid-cols-[260px_minmax(0,1fr)_minmax(0,1.15fr)]">
        {/* ------------------------------------------------ left: categories + objects */}
        <aside className="space-y-4">
          <nav aria-label="SQL categories" className="rounded-lg border border-rule bg-surface">
            {catalog.data?.categories.map((c) => {
              const open = openCats.has(c.id)
              return (
                <div key={c.id} className="border-b border-rule last:border-0">
                  <button type="button" aria-expanded={open}
                    onClick={() => setOpenCats((s) => { const n = new Set(s); if (n.has(c.id)) n.delete(c.id); else n.add(c.id); return n })}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm font-semibold hover:bg-paper">
                    {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                    <span className="flex-1">{c.title}</span>
                    <span className="text-xs font-normal text-muted">{c.count}</span>
                  </button>
                  {open && (
                    <ul className="pb-2">
                      {(byCategory.get(c.id) ?? []).map((e) => (
                        <li key={e.id}>
                          <button type="button" onClick={() => setSelectedId(e.id)}
                            className={cx('flex w-full items-center gap-2 py-1.5 pr-3 pl-9 text-left text-sm',
                              selectedId === e.id ? 'bg-bubble-soft font-semibold' : 'text-ink-soft hover:bg-paper')}>
                            <span className="flex-1">{e.title}</span>
                            {!e.allowed && <Lock className="size-3.5 text-muted" aria-label="administrators only" />}
                            {e.destructive && <ShieldAlert className="size-3.5 text-amber" aria-label="needs confirmation" />}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )
            })}
            {user?.role === 'ADMIN' && (
              <button type="button" onClick={() => setSelectedId(FREEFORM)}
                className={cx('flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm font-semibold',
                  isFree ? 'bg-bubble-soft' : 'hover:bg-paper')}>
                <SquareTerminal className="size-4" /> Free-form lab SQL
              </button>
            )}
          </nav>

          <section className="rounded-lg border border-rule bg-surface">
            <div className="flex items-center justify-between border-b border-rule px-3 py-2">
              <h2 className="text-sm font-semibold">Objects in {objects.data?.database ?? '…'}</h2>
              <button type="button" onClick={() => setObjectsTick((t) => t + 1)} aria-label="Refresh objects" className="rounded p-1 hover:bg-paper">
                <RefreshCw className={cx('size-3.5', objects.loading && 'animate-spin')} />
              </button>
            </div>
            <ul className="max-h-72 overflow-y-auto px-3 py-2 text-sm">
              {(objects.data?.tables ?? []).map((t) => (
                <li key={t.name} className="flex justify-between gap-2 py-0.5">
                  <span className={cx('font-mono text-xs', t.type === 'VIEW' && 'italic text-teal', t.name.startsWith('demo_') && 'rounded bg-bubble-soft px-1')}>{t.name}</span>
                  <span className="text-xs text-muted tabular-nums">{t.type === 'VIEW' ? 'view' : fmtNumber(t.row_count)}</span>
                </li>
              ))}
            </ul>
          </section>
        </aside>

        {/* ------------------------------------------------ center: statement + controls */}
        <section className="min-w-0 space-y-4">
          {isFree ? (
            <div className="rounded-lg border border-rule bg-surface p-4">
              <h2 className="text-lg font-bold">Free-form lab SQL</h2>
              {cfg?.freeform_enabled ? (
                <p className="mt-1 text-sm text-muted">
                  Runs statement by statement in one session as <span className="font-mono">{cfg.accounts.lab}</span>, which can only touch
                  {' '}<span className="font-mono">{cfg.lab_database}</span>. System schemas, privileges and server settings are refused;
                  data-changing statements ask for confirmation. Limits: {cfg.max_rows} rows, {cfg.timeout_seconds} s per statement.
                </p>
              ) : (
                <div className="mt-2"><Callout tone="warning">Free-form SQL is disabled. Set <code>SQL_FREEFORM_ENABLED=true</code> in .env and restart the API.</Callout></div>
              )}
              <div className="mt-3">
                <Field label="SQL" hint={`${freeSql.length}/${cfg?.max_sql_chars ?? 10000} characters · separate statements with ;`}>
                  <Textarea rows={12} value={freeSql} onChange={(e) => setFreeSql(e.target.value)} spellCheck={false}
                    className="font-mono text-[13px] leading-relaxed" maxLength={cfg?.max_sql_chars} />
                </Field>
              </div>
              <div className="mt-3 flex gap-2">
                <Button busy={execute.busy} disabled={!cfg?.freeform_enabled || !freeSql.trim()} onClick={() => run('run')}>
                  <Play className="size-4" /> Run
                </Button>
              </div>
            </div>
          ) : selected && (
            <div className="rounded-lg border border-rule bg-surface p-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="text-sm text-muted">{catalog.data?.categories.find((c) => c.id === selected.category)?.title}</p>
                  <h2 className="text-lg font-bold">{selected.title}</h2>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {selected.destructive && <Badge tone="SUBMITTED">needs confirmation</Badge>}
                  {selected.min_role === 'ADMIN' && <Badge tone="ADMIN">admin</Badge>}
                </div>
              </div>
              <p className="mt-2 text-sm">{selected.description}</p>

              {selected.params.length > 0 && (
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  {selected.params.map((p) => (
                    <Field key={p.name} label={p.label}
                      hint={p.type === 'text' ? `bound as a parameter · max ${p.max_length} chars` : `${p.min ?? ''} – ${p.max ?? ''}`}>
                      <Input value={params[p.name] ?? ''} type={p.type === 'text' ? 'text' : 'number'}
                        step={p.type === 'decimal' ? 'any' : 1} onChange={(e) => setParams({ ...params, [p.name]: e.target.value })} />
                    </Field>
                  ))}
                </div>
              )}

              <h3 className="mt-4 mb-2 text-sm font-semibold">Statements ({selected.steps.length})</h3>
              <ol className="space-y-2">
                {selected.steps.map((s, i) => (
                  <li key={i}>
                    <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                      <span className="font-semibold text-ink">{i + 1}. {s.title}</span>
                      <span>{ROLE_LABEL[s.role] ?? s.role}</span>
                      {s.conn !== selected.account && <span className="rounded bg-ink/8 px-1.5">session: {s.conn}</span>}
                      {s.expect_error && <span className="rounded bg-amber-soft px-1.5 text-amber">expected to fail</span>}
                    </div>
                    <SqlBlock sql={s.sql} wrap />
                  </li>
                ))}
              </ol>

              <div className="mt-4 flex flex-wrap gap-2">
                <Button busy={execute.busy} disabled={!selected.allowed} onClick={() => run('run')}><Play className="size-4" /> Run</Button>
                {selected.has_cleanup && (
                  <Button variant="secondary" disabled={!selected.allowed || execute.busy} onClick={() => run('cleanup')}>
                    <Eraser className="size-4" /> Clean up
                  </Button>
                )}
              </div>
              {!selected.allowed && <p className="mt-2 text-sm text-muted">This example needs an administrator account.</p>}
              {selected.has_cleanup && (
                <details className="mt-3 text-sm">
                  <summary className="cursor-pointer text-muted">Cleanup statements</summary>
                  <div className="mt-2 space-y-2">{selected.cleanup.map((c, i) => <SqlBlock key={i} sql={c.sql} />)}</div>
                </details>
              )}
              <div className="mt-4"><Callout>{selected.explanation}</Callout></div>
            </div>
          )}
        </section>

        {/* ------------------------------------------------ right: results */}
        <section className="min-w-0 space-y-3" aria-live="polite">
          <ErrorBanner error={execute.error} />
          {execute.busy && <Spinner label="Executing on MySQL" />}
          {!result && !execute.busy && !execute.error && (
            <div className="rounded-lg border border-dashed border-rule p-8 text-center text-sm text-muted">
              Results, affected rows, errors and timings appear here after you run.
            </div>
          )}
          {result && !execute.busy && <RunView result={result} />}
        </section>
      </div>

      <Modal open={!!confirm} title="Confirm this change" onClose={() => setConfirm(null)}
        footer={<><Button variant="secondary" onClick={() => setConfirm(null)}>Cancel</Button>
          <Button variant="danger" busy={execute.busy} onClick={() => confirm && execute.run(confirm.action, true)}>Run it</Button></>}>
        <p>These statements change or remove objects or rows in <span className="font-mono">{dbName}</span>.</p>
        {Array.isArray((confirm?.details as { statements?: string[] } | undefined)?.statements) && (
          <ul className="mt-3 list-disc space-y-1 pl-5 font-mono text-xs">
            {(confirm!.details as { statements: string[] }).statements.map((s, i) => <li key={i}>{s}</li>)}
          </ul>
        )}
        {targetDb === 'lab' && <p className="mt-3 text-sm text-muted">The lab database can be rebuilt at any time from the admin dashboard.</p>}
      </Modal>
    </div>
  )
}

export function RunView({ result }: { result: RunResult }) {
  const counts = result.steps.reduce<Record<string, number>>((acc, s) => ({ ...acc, [s.status]: (acc[s.status] ?? 0) + 1 }), {})
  const groups = useMemo(() => {
    const map = new Map<string, StepResult[]>()
    for (const s of result.steps) if (s.compare && s.result_sets?.length) map.set(s.compare, [...(map.get(s.compare) ?? []), s])
    return [...map.entries()].filter(([, v]) => v.length >= 2)
  }, [result])
  const t = result.timing_comparison

  return (
    <div className="space-y-3">
      <div className={cx('rounded-lg border px-4 py-3', result.status === 'success' ? 'border-teal/30 bg-teal-soft' : 'border-danger/30 bg-danger-soft')}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-semibold">{result.status === 'success' ? 'Executed' : 'Stopped at an error'} · {result.title}</p>
          <span className="text-sm tabular-nums">{fmtMs(result.total_duration_ms)}</span>
        </div>
        <p className="mt-0.5 text-xs text-muted">
          {result.mode.toLowerCase()} on <span className="font-mono">{result.database}</span> as <span className="font-mono">{result.account}</span>
          {' · '}{Object.entries(counts).map(([k, v]) => `${v} ${STATUS_STYLE[k]?.label ?? k}`).join(', ')}
          {' · '}request {result.request_id.slice(0, 8)}
        </p>
      </div>

      {t && (
        <div className="rounded-lg border border-rule bg-surface p-4">
          <p className="flex items-center gap-2 font-semibold"><Timer className="size-4" /> Measured comparison (median of 7 runs)</p>
          <div className="mt-2 grid grid-cols-3 gap-3 text-center">
            <div><div className="text-xs text-muted">without index</div><div className="text-xl font-bold tabular-nums">{fmtMs(t.before_median_ms)}</div></div>
            <div><div className="text-xs text-muted">with index</div><div className="text-xl font-bold tabular-nums">{fmtMs(t.after_median_ms)}</div></div>
            <div><div className="text-xs text-muted">speed-up</div><div className="text-xl font-bold tabular-nums">{t.speedup ? `${t.speedup}x` : '—'}</div></div>
          </div>
          <p className="mt-2 text-sm">Verdict from these measurements: <strong>{t.verdict}</strong>.</p>
          <p className="mt-1 text-xs text-muted">Runs (ms) before: {t.before_runs_ms.join(', ')} · after: {t.after_runs_ms.join(', ')}</p>
        </div>
      )}

      {groups.map(([key, steps]) => {
        const first = steps[0]
        const last = steps[steps.length - 1]
        return (
          <div key={key} className="min-w-0 rounded-lg border border-rule bg-surface p-4">
            <p className="mb-2 text-sm font-semibold">Comparison: {first.title} → {last.title}</p>
            <div className="grid gap-3 2xl:grid-cols-2">
              <div className="min-w-0"><p className="mb-1 text-xs text-muted">{first.title}</p><ResultGrid result={first.result_sets![0]} maxHeight={220} /></div>
              <div className="min-w-0"><p className="mb-1 text-xs text-muted">{last.title} <span className="rounded bg-bubble-soft px-1">highlight = new or changed</span></p>
                <ResultGrid result={last.result_sets![0]} highlight={diffRows(first.result_sets![0], last.result_sets![0])} maxHeight={220} /></div>
            </div>
          </div>
        )
      })}

      <ol className="space-y-2">
        {result.steps.map((s, i) => <StepCard key={i} index={i + 1} step={s} />)}
      </ol>
    </div>
  )
}

function StepCard({ step, index }: { step: StepResult; index: number }) {
  const [open, setOpen] = useState(step.status !== 'not_run' && step.status !== 'skipped')
  const style = STATUS_STYLE[step.status] ?? STATUS_STYLE.error
  return (
    <li className="rounded-lg border border-rule bg-surface">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
        className="flex w-full flex-wrap items-center gap-2 px-3 py-2 text-left text-sm">
        {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
        <span className="flex-1 font-semibold">{index}. {step.title}</span>
        <span className={cx('rounded px-2 py-0.5 text-xs font-semibold', style.className)}>{style.label}</span>
        {step.duration_ms !== undefined && <span className="text-xs text-muted tabular-nums">{fmtMs(step.duration_ms)}{step.repeat > 1 ? ' median' : ''}</span>}
      </button>
      {open && (
        <div className="space-y-2 border-t border-rule px-3 py-3">
          <p className="text-xs text-muted">session <span className="font-mono">{step.connection}</span> · account <span className="font-mono">{step.account}</span></p>
          <SqlBlock sql={step.sql} wrap />
          {step.error && (
            <div className={cx('rounded-md px-3 py-2 text-sm', step.status === 'expected_error' ? 'bg-amber-soft' : 'bg-danger-soft')}>
              <span className="font-semibold">MySQL error {step.error.code ?? ''}:</span> {step.error.message}
            </div>
          )}
          {step.note && <p className="text-xs text-muted">{step.note}</p>}
          {step.affected_rows !== undefined && step.affected_rows !== null && !step.result_sets?.length && (
            <p className="text-sm">Query OK · <strong>{step.affected_rows}</strong> row{step.affected_rows === 1 ? '' : 's'} affected</p>
          )}
          {step.result_sets?.map((rs, i) => (
            <div key={i}>
              {(step.result_sets?.length ?? 0) > 1 && <p className="mb-1 text-xs font-semibold text-muted">Result set {i + 1}</p>}
              <ResultGrid result={rs} maxHeight={260} />
            </div>
          ))}
          {step.timings_ms && <p className="text-xs text-muted">Measured runs (ms): {step.timings_ms.join(', ')}</p>}
        </div>
      )}
    </li>
  )
}
