import { Plus } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { RecordTable } from '../components/data'
import { Badge, Button, ErrorBanner, PageHeader, Panel, Select, Spinner, useToast } from '../components/ui'
import { get, qs } from '../lib/api'
import { fmtDate, fmtNumber } from '../lib/format'
import { useLoad } from '../lib/hooks'
import type { Exam } from '../lib/types'
import ExamForm from './ExamForm'

export default function Exams() {
  const navigate = useNavigate()
  const toast = useToast()
  const [status, setStatus] = useState('')
  const [mine, setMine] = useState(false)
  const [creating, setCreating] = useState(false)
  const exams = useLoad(() => get<Exam[]>(`/exams${qs({ status, mine })}`), [status, mine])

  return (
    <div className="space-y-6">
      <PageHeader title="Examinations" description="Rows come from the exam_overview view: live question and attempt counts."
        actions={<Button onClick={() => setCreating(true)}><Plus className="size-4" /> New exam</Button>} />
      <ErrorBanner error={exams.error} onRetry={exams.reload} />
      <Panel flush title={`${exams.data?.length ?? 0} exams`} actions={
        <div className="flex items-center gap-3 text-sm">
          <label className="flex items-center gap-2"><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Mine only</label>
          <Select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status" className="w-40">
            <option value="">All statuses</option>
            {['SCHEDULED', 'ACTIVE', 'COMPLETED', 'CANCELLED'].map((s) => <option key={s} value={s}>{s.toLowerCase()}</option>)}
          </Select>
        </div>}>
        {exams.loading && !exams.data ? <Spinner /> : (
          <RecordTable<Exam> rows={exams.data ?? []}
            rowKey={(r) => r.exam_id} onRowClick={(r) => navigate(`/exams/${r.exam_id}`)}
            columns={[
              { key: 'exam_id', label: 'ID', align: 'right' },
              { key: 'title', label: 'Title', render: (r) => <span className="font-medium">{r.title}</span> },
              { key: 'subject', label: 'Subject' },
              { key: 'status', label: 'Status', render: (r) => <Badge>{r.status}</Badge> },
              { key: 'exam_date', label: 'Opens', render: (r) => fmtDate(r.exam_date) },
              { key: 'duration_minutes', label: 'Minutes', align: 'right' },
              { key: 'question_count', label: 'Questions', align: 'right' },
              { key: 'total_marks', label: 'Marks', align: 'right', render: (r) => fmtNumber(r.total_marks) },
              { key: 'attempt_count', label: 'Attempts', align: 'right' },
              { key: 'results_released', label: 'Results', render: (r) => r.results_released ? <Badge tone="PASS">released</Badge> : <span className="text-muted">hidden</span> },
              { key: 'created_by_name', label: 'Author' },
            ]} />
        )}
      </Panel>
      {creating && <ExamForm open onClose={() => setCreating(false)} onSaved={(e) => {
        setCreating(false)
        toast('success', 'Exam created')
        navigate(`/exams/${e.exam_id}`)
      }} />}
    </div>
  )
}
