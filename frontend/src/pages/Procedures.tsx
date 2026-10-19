import { Play } from 'lucide-react'
import { useEffect, useState } from 'react'
import { ResultGrid, SqlBlock } from '../components/data'
import { Badge, Button, Callout, ErrorBanner, Field, Input, PageHeader, Panel, Spinner } from '../components/ui'
import { get, post, qs } from '../lib/api'
import { cx, fmtMs } from '../lib/format'
import { useAction, useLoad } from '../lib/hooks'
import type { ResultSet } from '../lib/types'
import type { Objects } from './ObjectsExplorer'
import { DatabasePicker } from './SchemaExplorer'

interface CallResult {
  status: 'success' | 'error'; routine: string; database: string; statements: string[]
  result_sets: ResultSet[]; duration_ms: number; error?: { code: number | null; message: string }
}

const READ_ONLY = ['fn_marks_percentage', 'fn_result_status', 'getexamdetails', 'getstudentresults', 'sp_exam_attempt_stats']
const SAMPLE_ARGS: Record<string, string[]> = {
  fn_marks_percentage: ['13.5', '17'], fn_result_status: ['39.5', '40'], GetExamDetails: ['1'],
  GetStudentResults: ['1'], sp_exam_attempt_stats: ['2'], sp_finalize_attempt: ['1'],
}

export default function Procedures() {
  const [database, setDatabase] = useState('main')
  const objects = useLoad(() => get<Objects>(`/db/objects${qs({ database })}`), [database])
  const [name, setName] = useState<string | null>(null)
  const [args, setArgs] = useState<string[]>([])
  const [result, setResult] = useState<CallResult | null>(null)

  const routines = (objects.data?.routines ?? []).filter((r) => !r.name.startsWith('sp_seed') && r.name !== 'sp_generate_bulk_data')
  const routine = routines.find((r) => r.name === name) ?? null
  const inputs = routine ? routine.parameters.filter((p) => routine.type === 'FUNCTION' || p.mode === 'IN') : []
  const runnable = !!routine && (database === 'lab' || READ_ONLY.includes(routine.name.toLowerCase()))

  useEffect(() => {
    if (!name && routines.length) setName(routines.find((r) => r.name === 'GetExamDetails')?.name ?? routines[0].name)
  }, [routines, name])
  useEffect(() => {
    if (routine) setArgs(SAMPLE_ARGS[routine.name] ?? inputs.map(() => ''))
    setResult(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routine?.name, database])

  const call = useAction(async () => {
    setResult(await post<CallResult>(`/db/routines/${routine!.name}/call`, {
      database, args: args.map((a) => (a.trim() === '' ? null : a)),
    }))
  })

  return (
    <div className="space-y-6">
      <PageHeader title="Stored procedures & functions" description="Run a stored routine with your own arguments and see exactly what MySQL returns."
        actions={<DatabasePicker value={database} onChange={(d) => { setDatabase(d); setName(null) }} />} />
      <Callout>
        A <strong>procedure</strong> is invoked with <code>CALL</code>, may return several result sets and hand values back through
        OUT parameters. A <strong>function</strong> returns exactly one value and can be used inside any expression,
        e.g. <code>SELECT fn_marks_percentage(marks, total) FROM …</code>. All OEMS routines use SQL SECURITY INVOKER, so they run
        with the caller's privileges — on the application database the read-only account may run only the read-only routines.
      </Callout>
      <ErrorBanner error={objects.error} onRetry={objects.reload} />
      {objects.loading && !objects.data ? <Spinner /> : (
        <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
          <Panel flush title={`${routines.length} routines in ${objects.data?.database}`}>
            <ul className="divide-y divide-rule">
              {routines.map((r) => (
                <li key={r.name}>
                  <button type="button" onClick={() => setName(r.name)}
                    className={cx('w-full px-4 py-2.5 text-left hover:bg-paper', name === r.name && 'bg-bubble-soft')}>
                    <span className="font-mono text-sm font-semibold">{r.name}</span>
                    <span className="mt-0.5 flex gap-2 text-xs text-muted"><Badge>{r.type}</Badge>{r.data_access.toLowerCase()}</span>
                  </button>
                </li>
              ))}
            </ul>
          </Panel>

          {routine && (
            <div className="min-w-0 space-y-4">
              <Panel title={<span className="font-mono">{routine.name}</span>}
                actions={<span className="text-xs text-muted">{routine.type} · SQL SECURITY {routine.security_type} · deterministic: {routine.is_deterministic.toLowerCase()}</span>}>
                {routine.comment && <p className="mb-3 text-sm">{routine.comment}</p>}
                <table className="mb-3 text-sm">
                  <tbody>
                    {routine.parameters.map((p) => (
                      <tr key={p.position}><td className="pr-4 text-muted">{p.mode ?? 'IN'}</td><td className="pr-4 font-mono">{p.name}</td><td className="font-mono text-xs">{p.type}</td></tr>
                    ))}
                    {routine.returns && <tr><td className="pr-4 text-muted">RETURNS</td><td colSpan={2} className="font-mono text-xs">{routine.returns}</td></tr>}
                  </tbody>
                </table>
                {routine.definition_visible ? <details><summary className="cursor-pointer text-sm text-muted">Body</summary><SqlBlock sql={routine.definition!} className="mt-2 max-h-80" /></details>
                  : <p className="text-sm text-muted">The body is hidden from this account (needs SHOW_ROUTINE).</p>}
              </Panel>

              <Panel title="Execute">
                {!runnable ? (
                  <Callout tone="warning">This routine changes data, so it can only be executed on the lab database. Switch the database above.</Callout>
                ) : (
                  <>
                    <div className="grid gap-3 sm:grid-cols-3">
                      {inputs.map((p, i) => (
                        <Field key={p.position} label={p.name} hint={p.type}>
                          <Input value={args[i] ?? ''} onChange={(e) => setArgs(args.map((a, j) => (j === i ? e.target.value : a)))} />
                        </Field>
                      ))}
                    </div>
                    <div className="mt-3 flex items-center gap-3">
                      <Button busy={call.busy} onClick={() => call.run()}><Play className="size-4" /> {routine.type === 'FUNCTION' ? 'Evaluate' : 'CALL'}</Button>
                      <span className="text-xs text-muted">Arguments are sent as bound parameters. Try an id that does not exist.</span>
                    </div>
                  </>
                )}
                <div className="mt-3"><ErrorBanner error={call.error} /></div>
                {result && (
                  <div className="mt-4 space-y-3">
                    {result.statements.map((s, i) => <SqlBlock key={i} sql={s} />)}
                    {result.error && (
                      <div className="rounded-md bg-danger-soft px-3 py-2 text-sm"><strong>MySQL error {result.error.code}:</strong> {result.error.message}</div>
                    )}
                    {result.result_sets.map((rs, i) => (
                      <div key={i}>
                        <p className="mb-1 text-xs font-semibold text-muted">Result set {i + 1}</p>
                        <ResultGrid result={rs} />
                      </div>
                    ))}
                    <p className="text-xs text-muted">{result.status === 'success' ? 'Completed' : 'Failed'} in {fmtMs(result.duration_ms)} on {result.database}</p>
                  </div>
                )}
              </Panel>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
