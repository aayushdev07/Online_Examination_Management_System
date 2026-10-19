import { useNavigate } from 'react-router-dom'
import { RecordTable } from '../components/data'
import { Badge, ErrorBanner, PageHeader, Panel, Spinner, Stat } from '../components/ui'
import { get, qs } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtDate, fmtNumber } from '../lib/format'
import { useLoad } from '../lib/hooks'
import type { Exam, Page } from '../lib/types'

export interface PerfRow {
  exam_id: number; title: string; subject: string; status: string; attempt_count: number; evaluated_count: number
  avg_percentage: number | null; min_percentage: number | null; max_percentage: number | null
  pass_count: number; pass_rate: number | null
}
interface AttemptItem { attempt_id: number; exam_id: number; exam_title: string; student_name: string; submitted_at: string }

export function PerformanceTable({ rows }: { rows: PerfRow[] }) {
  const navigate = useNavigate()
  return (
    <RecordTable<PerfRow> rows={rows} rowKey={(r) => r.exam_id} onRowClick={(r) => navigate(`/exams/${r.exam_id}`)}
      columns={[
        { key: 'title', label: 'Exam', render: (r) => <span className="font-medium">{r.title}</span> },
        { key: 'status', label: 'Status', render: (r) => <Badge>{r.status}</Badge> },
        { key: 'attempt_count', label: 'Attempts', align: 'right', render: (r) => fmtNumber(r.attempt_count) },
        { key: 'evaluated_count', label: 'Evaluated', align: 'right', render: (r) => fmtNumber(r.evaluated_count) },
        { key: 'avg_percentage', label: 'Avg %', align: 'right', render: (r) => fmtNumber(r.avg_percentage) },
        { key: 'range', label: 'Min–max %', align: 'right', render: (r) => r.min_percentage === null ? '—' : `${fmtNumber(r.min_percentage)}–${fmtNumber(r.max_percentage)}` },
        { key: 'pass_rate', label: 'Pass rate', align: 'right', render: (r) => r.pass_rate === null ? '—' : (
          <span className="inline-flex items-center gap-2">
            <span className="h-1.5 w-16 overflow-hidden rounded bg-rule"><span className="block h-full bg-teal" style={{ width: `${r.pass_rate}%` }} /></span>
            {fmtNumber(r.pass_rate, 1)}%
          </span>) },
      ]} />
  )
}

export default function FacultyDashboard() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const exams = useLoad(() => get<Exam[]>('/exams'))
  const perf = useLoad(() => get<PerfRow[]>('/results/performance'))
  const grading = useLoad(() => get<Page<AttemptItem>>(`/attempts${qs({ status: 'SUBMITTED', page_size: 10 })}`))

  if (exams.loading && !exams.data) return <Spinner />
  const list = exams.data ?? []
  const mine = list.filter((e) => e.created_by === user?.id)
  const active = list.filter((e) => e.status === 'ACTIVE')

  return (
    <div className="space-y-6">
      <PageHeader title={`Welcome, ${user?.name}`} description="Your examinations, grading queue and class performance." />
      <ErrorBanner error={exams.error ?? perf.error ?? grading.error} />
      <div className="grid gap-3 sm:grid-cols-4">
        <Stat label="All exams" value={list.length} hint={`${mine.length} created by you`} />
        <Stat label="Active now" value={active.length} tone={active.length ? 'teal' : 'ink'} />
        <Stat label="Waiting for grading" value={grading.data?.total ?? '—'} tone={grading.data?.total ? 'amber' : 'ink'} />
        <Stat label="Attempts recorded" value={fmtNumber(list.reduce((s, e) => s + (e.attempt_count ?? 0), 0))} />
      </div>
      <div className="grid gap-6 xl:grid-cols-[2fr_1fr]">
        <Panel flush title="Performance by exam (exam_performance_view)">
          {perf.data ? <PerformanceTable rows={perf.data} /> : <Spinner />}
        </Panel>
        <Panel flush title="Grading queue">
          {(grading.data?.items ?? []).length === 0 ? <p className="p-4 text-sm text-muted">No submitted attempts are waiting.</p> : (
            <ul className="divide-y divide-rule">
              {grading.data!.items.map((a) => (
                <li key={a.attempt_id}>
                  <button type="button" onClick={() => navigate(`/attempts/${a.attempt_id}`)} className="w-full px-4 py-3 text-left hover:bg-paper">
                    <p className="font-medium">{a.student_name}</p>
                    <p className="text-sm text-muted">{a.exam_title} · {fmtDate(a.submitted_at)}</p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  )
}
