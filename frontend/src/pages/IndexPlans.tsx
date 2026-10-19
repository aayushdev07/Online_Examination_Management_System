import { FlaskConical, Play } from 'lucide-react'
import { useState } from 'react'
import { ResultGrid } from '../components/data'
import { Button, Callout, ErrorBanner, PageHeader, Panel, Select, Spinner, Textarea } from '../components/ui'
import { get, post, qs } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtMs, fmtNumber } from '../lib/format'
import { useAction, useLoad } from '../lib/hooks'
import type { ResultSet, RunResult } from '../lib/types'
import { DatabasePicker, type Schema } from './SchemaExplorer'

interface Plan extends ResultSet { duration_ms: number }
interface ExplainResult { database: string; account: string; statement: string; plans: { table: Plan; tree: Plan; analyze?: Plan } }

const SAMPLES = [
  { label: 'Lookup by email (unique index)', sql: "SELECT * FROM student WHERE email = 'aarav.shah@students.oems.edu'" },
  { label: 'Function on an indexed column', sql: "SELECT * FROM student WHERE LOWER(email) = 'aarav.shah@students.oems.edu'" },
  { label: 'Attempts of a student in an exam', sql: 'SELECT * FROM attempt WHERE student_id = 1 AND exam_id = 1' },
  { label: 'Questions of an exam', sql: 'SELECT q.* FROM exam_question eq JOIN question q ON q.question_id = eq.question_id WHERE eq.exam_id = 1 ORDER BY eq.question_order' },
  { label: 'Average per subject (join + group)', sql: 'SELECT e.subject, AVG(r.percentage) FROM result r JOIN attempt a ON a.attempt_id = r.attempt_id JOIN exam e ON e.exam_id = a.exam_id GROUP BY e.subject' },
  { label: 'Answers in a time window (no index)', sql: "SELECT COUNT(*) FROM answer WHERE answered_at >= NOW() - INTERVAL 41 DAY AND answered_at < NOW() - INTERVAL 40 DAY" },
]

export default function IndexPlans() {
  const { user } = useAuth()
  const [database, setDatabase] = useState('main')
  const [sql, setSql] = useState(SAMPLES[0].sql)
  const [analyze, setAnalyze] = useState(true)
  const [plan, setPlan] = useState<ExplainResult | null>(null)
  const [experiment, setExperiment] = useState<RunResult | null>(null)
  const schema = useLoad(() => get<Schema>(`/db/schema${qs({ database })}`), [database])

  const explain = useAction(async () => setPlan(await post<ExplainResult>('/db/explain', { database, sql, analyze })))
  const runExperiment = useAction(async () => {
    const res = await post<RunResult>('/sql/execute', { example_id: 'idx_create_compare', confirm: true })
    await post('/sql/execute', { example_id: 'idx_create_compare', action: 'cleanup' })
    setExperiment(res)
    schema.reload()
  })

  const indexes = (schema.data?.tables ?? []).filter((t) => t.type !== 'VIEW')
    .flatMap((t) => t.indexes.map((i) => [t.name, i.name, i.columns, i.is_unique ? 'yes' : 'no', i.cardinality] as (string | number | null)[]))

  return (
    <div className="space-y-6">
      <PageHeader title="Indexes & query plans" description="EXPLAIN shows the plan MySQL chooses; EXPLAIN ANALYZE also executes the query and reports real timings."
        actions={<DatabasePicker value={database} onChange={setDatabase} />} />

      <div className="grid gap-6 xl:grid-cols-[1.2fr_1fr]">
        <Panel title="Query plan viewer">
          <label className="mb-1 block text-sm font-medium" htmlFor="plan-sample">Sample query</label>
          <Select id="plan-sample" onChange={(e) => setSql(SAMPLES[Number(e.target.value)].sql)} className="mb-3">
            {SAMPLES.map((s, i) => <option key={i} value={i}>{s.label}</option>)}
          </Select>
          <Textarea rows={5} value={sql} onChange={(e) => setSql(e.target.value)} spellCheck={false} className="font-mono text-[13px]" aria-label="SELECT statement" />
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Button busy={explain.busy} onClick={() => explain.run()}><Play className="size-4" /> Explain</Button>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={analyze} onChange={(e) => setAnalyze(e.target.checked)} /> Also EXPLAIN ANALYZE (executes the query)</label>
          </div>
          <p className="mt-2 text-xs text-muted">Only single SELECT statements are accepted. The application database is explained through the read-only account.</p>
          <div className="mt-3"><ErrorBanner error={explain.error} /></div>
          {plan && (
            <div className="mt-4 space-y-4">
              <div>
                <p className="mb-1 text-sm font-semibold">EXPLAIN (estimated plan) <span className="font-normal text-muted">· {fmtMs(plan.plans.table.duration_ms)}</span></p>
                <ResultGrid result={plan.plans.table} />
                <p className="mt-1 text-xs text-muted">type: const/eq_ref/ref use an index for lookups; range scans part of an index; ALL is a full table scan. key = the index chosen; rows = estimated rows examined.</p>
              </div>
              <div>
                <p className="mb-1 text-sm font-semibold">EXPLAIN FORMAT=TREE</p>
                <pre className="sql overflow-x-auto rounded-md border border-rule bg-paper p-3 text-xs">{String(plan.plans.tree.rows[0]?.[0] ?? '')}</pre>
              </div>
              {plan.plans.analyze && (
                <div>
                  <p className="mb-1 text-sm font-semibold">EXPLAIN ANALYZE (measured) <span className="font-normal text-muted">· executed in {fmtMs(plan.plans.analyze.duration_ms)}</span></p>
                  <pre className="sql overflow-x-auto rounded-md border border-rule bg-paper p-3 text-xs">{String(plan.plans.analyze.rows[0]?.[0] ?? '')}</pre>
                </div>
              )}
            </div>
          )}
        </Panel>

        <div className="min-w-0 space-y-6">
          <Panel title={<span className="flex items-center gap-2"><FlaskConical className="size-4" /> Measured index experiment</span>}>
            <p className="text-sm text-muted">Times a range query on <code>answer.answered_at</code> in the lab database (warm-up + 7 runs), creates an index, times it again and drops the index. Nothing here is estimated.</p>
            {user?.role === 'ADMIN' ? (
              <Button className="mt-3" busy={runExperiment.busy} onClick={() => runExperiment.run()}><Play className="size-4" /> Run experiment</Button>
            ) : <div className="mt-3"><Callout tone="warning">Creating and dropping indexes requires an administrator.</Callout></div>}
            <div className="mt-3"><ErrorBanner error={runExperiment.error} /></div>
            {runExperiment.busy && <Spinner label="Measuring" />}
            {experiment?.timing_comparison && !runExperiment.busy && (
              <div className="mt-4 space-y-3">
                <div className="grid grid-cols-3 gap-3 text-center">
                  <div className="rounded-md bg-paper p-2"><div className="text-xs text-muted">without index</div><div className="text-lg font-bold tabular-nums">{fmtMs(experiment.timing_comparison.before_median_ms)}</div></div>
                  <div className="rounded-md bg-paper p-2"><div className="text-xs text-muted">with index</div><div className="text-lg font-bold tabular-nums">{fmtMs(experiment.timing_comparison.after_median_ms)}</div></div>
                  <div className="rounded-md bg-bubble-soft p-2"><div className="text-xs text-muted">speed-up</div><div className="text-lg font-bold tabular-nums">{experiment.timing_comparison.speedup ?? '—'}x</div></div>
                </div>
                <p className="text-sm">Verdict: <strong>{experiment.timing_comparison.verdict}</strong>.</p>
                {experiment.steps.filter((s) => s.compare === 'plan').map((s, i) => (
                  <div key={i}><p className="mb-1 text-xs font-semibold text-muted">{s.title}</p>{s.result_sets?.[0] && <ResultGrid result={s.result_sets[0]} maxHeight={160} />}</div>
                ))}
                <p className="text-xs text-muted">Rows in answer: {fmtNumber(Number(experiment.steps.find((s) => s.role === 'info')?.result_sets?.[0]?.rows[0]?.[0] ?? 0))}. The demo index was dropped again afterwards.</p>
              </div>
            )}
          </Panel>

          <Panel flush title={`Indexes in ${schema.data?.database ?? '…'}`}>
            {schema.loading && !schema.data ? <Spinner /> : (
              <div className="p-3">
                <ResultGrid result={{ columns: ['table', 'index', 'columns', 'unique', 'cardinality'], rows: indexes, row_count: indexes.length, truncated: false }} maxHeight={480} />
              </div>
            )}
          </Panel>
        </div>
      </div>
    </div>
  )
}
