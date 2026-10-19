import { Play, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { ResultGrid, SqlBlock } from '../components/data'
import { Badge, Button, ErrorBanner, Field, Input, PageHeader, Panel, Spinner } from '../components/ui'
import { get, post, qs } from '../lib/api'
import { cx, fmtDate, fmtMs } from '../lib/format'
import { useAction, useLoad } from '../lib/hooks'
import type { Cell, RunResult } from '../lib/types'
import { DatabasePicker } from './SchemaExplorer'

export interface Objects {
  database: string
  views: { name: string; definition: string | null; security_type: string; is_updatable: string; definer: string }[]
  triggers: { name: string; timing: string; event: string; table_name: string; definition: string; created: string }[]
  routines: { name: string; type: string; returns: string | null; security_type: string; data_access: string
    is_deterministic: string; comment: string; definition: string | null; definition_visible: boolean
    parameters: { position: number; mode: string | null; name: string; type: string }[] }[]
}
interface Rows { columns: string[]; rows: Cell[][]; total: number; duration_ms: number }

export default function ObjectsExplorer() {
  const [database, setDatabase] = useState('main')
  const objects = useLoad(() => get<Objects>(`/db/objects${qs({ database })}`), [database])
  const [viewName, setViewName] = useState<string | null>(null)
  const viewRows = useLoad(() => viewName
    ? get<Rows>(`/db/tables/${viewName}/rows${qs({ database, page_size: 25 })}`) : Promise.resolve(null), [viewName, database])
  const audit = useLoad(() => get<Rows>(`/db/tables/exam_audit/rows${qs({ database, page_size: 8, sort: 'audit_id', direction: 'desc' })}`), [database])
  const [examId, setExamId] = useState('7')
  const [duration, setDuration] = useState('55')
  const [demo, setDemo] = useState<RunResult | null>(null)
  const runTrigger = useAction(async () => {
    setDemo(await post<RunResult>('/sql/execute', { example_id: 'trg_audit_duration', params: { exam_id: examId, new_duration: duration } }))
  })

  return (
    <div className="space-y-6">
      <PageHeader title="Views & triggers" description="Definitions are read live from information_schema.VIEWS and information_schema.TRIGGERS."
        actions={<><DatabasePicker value={database} onChange={(d) => { setDatabase(d); setViewName(null) }} />
          <Button variant="secondary" onClick={() => { objects.reload(); audit.reload() }}><RefreshCw className="size-4" /> Refresh</Button></>} />
      <ErrorBanner error={objects.error} onRetry={objects.reload} />
      {objects.loading && !objects.data ? <Spinner /> : objects.data && (
        <>
          <Panel title={`Views (${objects.data.views.length})`}>
            <div className="space-y-4">
              {objects.data.views.map((v) => (
                <div key={v.name} className="rounded-md border border-rule p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-mono font-semibold">{v.name}</p>
                    <div className="flex items-center gap-2 text-xs text-muted">
                      SQL SECURITY {v.security_type} · updatable: {v.is_updatable.toLowerCase()}
                      <Button variant="secondary" onClick={() => setViewName(viewName === v.name ? null : v.name)}>
                        <Play className="size-4" /> {viewName === v.name ? 'Hide rows' : 'SELECT * FROM view'}
                      </Button>
                    </div>
                  </div>
                  {v.definition && <details className="mt-2"><summary className="cursor-pointer text-sm text-muted">Stored definition</summary><SqlBlock sql={v.definition} className="mt-2 max-h-56" /></details>}
                  {viewName === v.name && (
                    <div className="mt-3">
                      <ErrorBanner error={viewRows.error} />
                      {viewRows.loading ? <Spinner /> : viewRows.data && (
                        <>
                          <ResultGrid result={{ columns: viewRows.data.columns, rows: viewRows.data.rows, row_count: viewRows.data.total, truncated: viewRows.data.total > viewRows.data.rows.length }} />
                          <p className="text-xs text-muted">Evaluated against the base tables right now in {fmtMs(viewRows.data.duration_ms)}.</p>
                        </>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </Panel>

          <Panel title={`Triggers (${objects.data.triggers.length})`} flush>
            <ul className="divide-y divide-rule">
              {objects.data.triggers.map((t) => (
                <li key={t.name} className="px-4 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono font-semibold">{t.name}</span>
                    <Badge tone={t.timing === 'BEFORE' ? 'SUBMITTED' : 'PASS'}>{`${t.timing} ${t.event}`}</Badge>
                    <span className="text-sm text-muted">on <span className="font-mono">{t.table_name}</span> · created {fmtDate(t.created)}</span>
                  </div>
                  <details className="mt-2"><summary className="cursor-pointer text-sm text-muted">Trigger body</summary><SqlBlock sql={t.definition} className="mt-2 max-h-72" /></details>
                </li>
              ))}
            </ul>
          </Panel>
        </>
      )}

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel title="Try the audit trigger (lab database)">
          <p className="mb-3 text-sm text-muted">Runs <code>UPDATE exam SET duration_minutes = …</code> in the lab database. No code writes to exam_audit — the AFTER UPDATE trigger does.</p>
          <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
            <Field label="Exam id"><Input type="number" value={examId} onChange={(e) => setExamId(e.target.value)} /></Field>
            <Field label="New duration (min)"><Input type="number" value={duration} onChange={(e) => setDuration(e.target.value)} /></Field>
            <Button busy={runTrigger.busy} onClick={() => runTrigger.run()}><Play className="size-4" /> Update exam</Button>
          </div>
          <div className="mt-3"><ErrorBanner error={runTrigger.error} /></div>
          {demo && (
            <div className="mt-4 space-y-3">
              {demo.steps.filter((s) => s.role === 'after' || s.role === 'main').map((s, i) => (
                <div key={i}>
                  <p className={cx('mb-1 text-sm font-semibold', s.status === 'error' && 'text-danger')}>
                    {s.title}{s.affected_rows !== undefined && s.affected_rows !== null ? ` — ${s.affected_rows} row(s) affected` : ''}
                  </p>
                  {s.error && <p className="text-sm text-danger">MySQL error {s.error.code}: {s.error.message}</p>}
                  {s.result_sets?.[0] && <ResultGrid result={s.result_sets[0]} maxHeight={200} />}
                </div>
              ))}
            </div>
          )}
        </Panel>
        <Panel title={`Latest exam_audit rows (${objects.data?.database ?? database})`} actions={<Button variant="secondary" onClick={audit.reload}>Refresh</Button>}>
          <ErrorBanner error={audit.error} />
          {audit.data && <ResultGrid result={{ columns: audit.data.columns, rows: audit.data.rows, row_count: audit.data.total, truncated: true }} maxHeight={420} />}
        </Panel>
      </div>
    </div>
  )
}
