import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { RecordTable, ResultGrid, SqlBlock } from '../components/data'
import { Badge, Button, Empty, ErrorBanner, Input, PageHeader, Pagination, Panel, Select, Spinner } from '../components/ui'
import { get, qs } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cx, fmtDate, fmtMs, fmtNumber } from '../lib/format'
import { useAction, useLoad } from '../lib/hooks'
import type { Exam, Page, ResultSet } from '../lib/types'

interface ResultRow {
  result_id: number; student_id: number; student_name: string; email: string; exam_id: number; exam_title: string
  subject: string; attempt_id: number; marks_obtained: number; total_marks: number; percentage: number
  result_status: string; evaluated_at: string
}
interface Report { id: string; title: string; description: string; sql: string }
interface ReportRun extends Report, Omit<ResultSet, 'truncated'> { duration_ms: number; account: string }

export default function Results() {
  const { user } = useAuth()
  const [tab, setTab] = useState<'results' | 'reports'>('results')
  const staff = user?.role !== 'STUDENT'
  return (
    <div className="space-y-6">
      <PageHeader title={staff ? 'Results & reports' : 'My results'}
        description={staff ? 'Results come from student_result_view; reports run on the read-only MySQL account.'
          : 'Only results the faculty has released are shown.'} />
      {staff && (
        <div role="tablist" className="flex gap-1 border-b border-rule">
          {(['results', 'reports'] as const).map((t) => (
            <button key={t} role="tab" type="button" aria-selected={tab === t} onClick={() => setTab(t)}
              className={cx('-mb-px border-b-2 px-4 py-2 text-sm font-semibold capitalize',
                tab === t ? 'border-ink' : 'border-transparent text-muted hover:text-ink')}>{t === 'results' ? 'Results' : 'SQL reports'}</button>
          ))}
        </div>
      )}
      {tab === 'results' ? <ResultsTable staff={staff} /> : <Reports />}
    </div>
  )
}

function ResultsTable({ staff }: { staff: boolean }) {
  const navigate = useNavigate()
  const [examId, setExamId] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const exams = useLoad(() => (staff ? get<Exam[]>('/exams') : Promise.resolve([] as Exam[])), [staff])
  const list = useLoad(() => get<Page<ResultRow>>(`/results${qs({ exam_id: examId, search, page, page_size: 25 })}`), [examId, search, page])

  return (
    <Panel flush title={`${(list.data?.total ?? 0).toLocaleString()} results`} actions={staff && (
      <div className="flex flex-wrap gap-2">
        <Select value={examId} onChange={(e) => { setExamId(e.target.value); setPage(1) }} className="w-64" aria-label="Filter by exam">
          <option value="">All exams</option>
          {(exams.data ?? []).map((e) => <option key={e.exam_id} value={e.exam_id}>{e.title}</option>)}
        </Select>
        <Input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1) }} placeholder="Student name or e-mail" className="w-56" aria-label="Search student" />
      </div>)}>
      <div className="px-4 pt-3"><ErrorBanner error={list.error} onRetry={list.reload} /></div>
      {list.loading && !list.data ? <Spinner /> : !staff && list.data?.total === 0 ? (
        <div className="p-4"><Empty title="No released results yet">Results appear after the faculty releases them.</Empty></div>
      ) : (
        <>
          <RecordTable<ResultRow> rows={list.data?.items ?? []} rowKey={(r) => r.result_id}
            onRowClick={(r) => navigate(`/attempts/${r.attempt_id}`)}
            columns={[
              ...(staff ? [{ key: 'student_name', label: 'Student', render: (r: ResultRow) => <span className="font-medium">{r.student_name}</span> }] : []),
              { key: 'exam_title', label: 'Exam' },
              { key: 'subject', label: 'Subject' },
              { key: 'marks', label: 'Marks', align: 'right', render: (r) => `${fmtNumber(r.marks_obtained)} / ${fmtNumber(r.total_marks)}` },
              { key: 'percentage', label: '%', align: 'right', render: (r) => fmtNumber(r.percentage) },
              { key: 'result_status', label: 'Result', render: (r) => <Badge>{r.result_status}</Badge> },
              { key: 'evaluated_at', label: 'Evaluated', render: (r) => fmtDate(r.evaluated_at) },
            ]} />
          {list.data && <Pagination page={page} pageSize={25} total={list.data.total} onPage={setPage} />}
        </>
      )}
    </Panel>
  )
}

function Reports() {
  const reports = useLoad(() => get<Report[]>('/reports'))
  const [selected, setSelected] = useState<string | null>(null)
  const [result, setResult] = useState<ReportRun | null>(null)
  const run = useAction(async (id: string) => {
    setSelected(id)
    setResult(await get<ReportRun>(`/reports/${id}`))
  })
  return (
    <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
      <Panel flush title="Reports (database/reports.sql)">
        <ErrorBanner error={reports.error} />
        <ul className="divide-y divide-rule">
          {(reports.data ?? []).map((r) => (
            <li key={r.id}>
              <button type="button" onClick={() => run.run(r.id)}
                className={cx('w-full px-4 py-3 text-left hover:bg-paper', selected === r.id && 'bg-bubble-soft')}>
                <p className="font-medium">{r.title}</p>
                <p className="text-xs text-muted">{r.description}</p>
              </button>
            </li>
          ))}
        </ul>
      </Panel>
      <div className="min-w-0 space-y-4">
        <ErrorBanner error={run.error} />
        {run.busy && <Spinner label="Running report" />}
        {!result && !run.busy && <Empty title="Choose a report">Each report is a single SQL statement executed on demand.</Empty>}
        {result && !run.busy && (
          <Panel title={result.title} actions={<span className="text-sm text-muted">{result.row_count} rows · {fmtMs(result.duration_ms)} · as {result.account}</span>}>
            <SqlBlock sql={result.sql} className="mb-4 max-h-64" />
            <ResultGrid result={{ ...result, truncated: false }} maxHeight={520} />
            <div className="mt-3"><Button variant="secondary" onClick={() => run.run(result.id)}>Run again</Button></div>
          </Panel>
        )}
      </div>
    </div>
  )
}
