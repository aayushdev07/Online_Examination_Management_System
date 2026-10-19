import { ArrowLeft, Eye, EyeOff, Pencil, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { RecordTable } from '../components/data'
import {
  Badge, Button, Callout, ErrorBanner, Field, Input, Modal, PageHeader, Panel, Select, Spinner, Stat, useToast,
} from '../components/ui'
import { del, get, post, put, qs } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cx, fmtDate, fmtNumber } from '../lib/format'
import { useAction, useLoad } from '../lib/hooks'
import type { Exam, Page, Question } from '../lib/types'
import ExamForm from './ExamForm'

interface Assigned {
  question_id: number; question_order: number; marks_assigned: number; question_text: string
  question_type: string; options: string[] | null; correct_answer: string | null; bank_marks: number
}
interface AttemptRow {
  attempt_id: number; student_id: number; student_name: string; email: string; status: string
  started_at: string; submitted_at: string | null; marks_obtained: number | null; percentage: number | null
  result_status: string | null; ungraded_answers: number
}
interface AuditRow {
  audit_id: number; action: string; changed_columns: string | null; old_title: string | null; new_title: string | null
  old_duration: number | null; new_duration: number | null; old_status: string | null; new_status: string | null
  old_exam_date: string | null; new_exam_date: string | null; db_user: string; changed_at: string
}

const TABS = ['Questions', 'Attempts', 'Audit trail'] as const

export default function ExamDetail() {
  const { examId } = useParams()
  const navigate = useNavigate()
  const toast = useToast()
  const { user } = useAuth()
  const [tab, setTab] = useState<(typeof TABS)[number]>('Questions')
  const [editing, setEditing] = useState(false)
  const [adding, setAdding] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const exam = useLoad(() => get<Exam>(`/exams/${examId}`), [examId])
  const questions = useLoad(() => get<{ questions: Assigned[] }>(`/exams/${examId}/questions`), [examId])
  const attempts = useLoad(() => get<AttemptRow[]>(`/exams/${examId}/attempts`), [examId])
  const audit = useLoad(() => get<AuditRow[]>(`/exams/${examId}/audit`), [examId])

  const refreshAll = () => { exam.reload(); questions.reload(); attempts.reload(); audit.reload() }

  const release = useAction(async (released: boolean) => {
    await post(`/exams/${examId}/release`, { released })
    toast('success', released ? 'Results released to students' : 'Results hidden from students')
    refreshAll()
  })
  const remove = useAction(async () => {
    await del(`/exams/${examId}`)
    toast('success', 'Exam deleted')
    navigate('/exams')
  })
  const unassign = useAction(async (qid: number) => {
    await del(`/exams/${examId}/questions/${qid}`)
    toast('success', 'Question removed — total marks recalculated by trigger')
    refreshAll()
  })
  const updateAssignment = useAction(async (qid: number, body: { question_order?: number; marks_assigned?: number }) => {
    await put(`/exams/${examId}/questions/${qid}`, body)
    toast('success', 'Assignment updated')
    refreshAll()
  })

  if (exam.loading && !exam.data) return <Spinner />
  if (!exam.data) return <ErrorBanner error={exam.error} onRetry={exam.reload} />
  const e = exam.data
  const canEdit = user?.role === 'ADMIN' || e.created_by === user?.id
  const locked = (e.attempt_count ?? 0) > 0
  const pending = (attempts.data ?? []).filter((a) => a.status === 'SUBMITTED').length

  return (
    <div className="space-y-6">
      <Link to="/exams" className="inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
        <ArrowLeft className="size-4" /> All exams
      </Link>
      <PageHeader title={e.title}
        description={<>{e.subject} · by {e.created_by_name} · exam #{e.exam_id}</>}
        actions={canEdit && <>
          <Button variant="secondary" onClick={() => setEditing(true)}><Pencil className="size-4" /> Edit</Button>
          <Button variant="secondary" busy={release.busy} onClick={() => release.run(!e.results_released)}>
            {e.results_released ? <><EyeOff className="size-4" /> Hide results</> : <><Eye className="size-4" /> Release results</>}
          </Button>
          <Button variant="danger" onClick={() => setConfirmDelete(true)}><Trash2 className="size-4" /> Delete</Button>
        </>} />
      <ErrorBanner error={release.error ?? remove.error ?? unassign.error ?? updateAssignment.error} />

      <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-6">
        <Stat label="Status" value={<Badge>{e.status}</Badge>} />
        <Stat label="Window" value={<span className="block text-sm leading-snug font-semibold">{fmtDate(e.exam_date)}<br />to {fmtDate(e.deadline)}</span>} />
        <Stat label="Duration" value={`${e.duration_minutes} min`} />
        <Stat label="Total marks" value={fmtNumber(e.total_marks)} hint={`${e.question_count} questions · pass ${fmtNumber(e.pass_percentage)}%`} />
        <Stat label="Attempts" value={e.attempt_count ?? 0} hint={`${e.submitted_count ?? 0} submitted`} />
        <Stat label="Waiting for grading" value={pending} tone={pending ? 'amber' : 'ink'} />
      </div>

      <div role="tablist" className="flex gap-1 border-b border-rule">
        {TABS.map((t) => (
          <button key={t} role="tab" type="button" aria-selected={tab === t} onClick={() => setTab(t)}
            className={cx('-mb-px border-b-2 px-4 py-2 text-sm font-semibold',
              tab === t ? 'border-ink text-ink' : 'border-transparent text-muted hover:text-ink')}>
            {t}{t === 'Attempts' ? ` (${e.attempt_count ?? 0})` : ''}
          </button>
        ))}
      </div>

      {tab === 'Questions' && (
        <Panel flush title="Assigned questions" actions={canEdit && !locked &&
          <Button onClick={() => setAdding(true)}><Plus className="size-4" /> Add from bank</Button>}>
          {locked && <div className="p-4 pb-0"><Callout tone="warning">Students have started this exam, so its questions are locked.</Callout></div>}
          <ErrorBanner error={questions.error} />
          <RecordTable<Assigned> rows={questions.data?.questions ?? []} rowKey={(r) => r.question_id}
            empty="No questions yet. Add some from the question bank."
            columns={[
              { key: 'question_order', label: '#', align: 'right', render: (r) => canEdit && !locked
                ? <InlineNumber value={r.question_order} min={1} step={1} onSave={(v) => updateAssignment.run(r.question_id, { question_order: v })} />
                : r.question_order },
              { key: 'question_text', label: 'Question', render: (r) => (
                <div className="max-w-xl">
                  <p>{r.question_text}</p>
                  {r.options && <p className="mt-1 text-xs text-muted">Options: {r.options.join(' / ')}</p>}
                  {r.correct_answer && <p className="text-xs text-teal">Key: {r.correct_answer}</p>}
                </div>) },
              { key: 'question_type', label: 'Type', render: (r) => <Badge>{r.question_type}</Badge> },
              { key: 'marks_assigned', label: 'Marks', align: 'right', render: (r) => canEdit && !locked
                ? <InlineNumber value={r.marks_assigned} min={0.5} step={0.5} onSave={(v) => updateAssignment.run(r.question_id, { marks_assigned: v })} />
                : fmtNumber(r.marks_assigned) },
              { key: 'actions', label: '', render: (r) => canEdit && !locked && (
                <Button variant="ghost" onClick={() => unassign.run(r.question_id)} aria-label={`Remove question ${r.question_order}`}>
                  <Trash2 className="size-4" /></Button>) },
            ]} />
        </Panel>
      )}

      {tab === 'Attempts' && (
        <Panel flush title="Student attempts" actions={<span className="text-sm text-muted">
          {(attempts.data?.length ?? 0) < (e.attempt_count ?? 0) ? `Showing ${attempts.data?.length} of ${e.attempt_count} (submitted first) · ` : ''}Open an attempt to review or grade it</span>}>
          <ErrorBanner error={attempts.error} />
          <RecordTable<AttemptRow> rows={attempts.data ?? []} rowKey={(r) => r.attempt_id}
            onRowClick={(r) => navigate(`/attempts/${r.attempt_id}`)} empty="No attempts yet."
            columns={[
              { key: 'attempt_id', label: 'Attempt', align: 'right' },
              { key: 'student_name', label: 'Student', render: (r) => <><span className="font-medium">{r.student_name}</span><br /><span className="text-xs text-muted">{r.email}</span></> },
              { key: 'status', label: 'Status', render: (r) => <Badge>{r.status}</Badge> },
              { key: 'submitted_at', label: 'Submitted', render: (r) => fmtDate(r.submitted_at) },
              { key: 'ungraded_answers', label: 'Ungraded', align: 'right', render: (r) => r.ungraded_answers ? <span className="font-semibold text-amber">{r.ungraded_answers}</span> : 0 },
              { key: 'marks_obtained', label: 'Marks', align: 'right', render: (r) => fmtNumber(r.marks_obtained) },
              { key: 'percentage', label: '%', align: 'right', render: (r) => fmtNumber(r.percentage) },
              { key: 'result_status', label: 'Result', render: (r) => r.result_status ? <Badge>{r.result_status}</Badge> : '—' },
            ]} />
        </Panel>
      )}

      {tab === 'Audit trail' && (
        <Panel flush title="exam_audit — written only by triggers" actions={<Button variant="secondary" onClick={audit.reload}>Refresh</Button>}>
          <ErrorBanner error={audit.error} />
          <RecordTable<AuditRow> rows={audit.data ?? []} rowKey={(r) => r.audit_id}
            columns={[
              { key: 'audit_id', label: 'ID', align: 'right' },
              { key: 'action', label: 'Action', render: (r) => <Badge>{r.action}</Badge> },
              { key: 'changed_columns', label: 'Changed' },
              { key: 'duration', label: 'Duration (old → new)', render: (r) => `${r.old_duration ?? '—'} → ${r.new_duration ?? '—'}` },
              { key: 'status', label: 'Status (old → new)', render: (r) => `${r.old_status ?? '—'} → ${r.new_status ?? '—'}` },
              { key: 'title', label: 'Title', render: (r) => r.old_title !== r.new_title && r.old_title && r.new_title
                ? <span className="text-xs">{r.old_title} → {r.new_title}</span> : <span className="text-xs">{r.new_title ?? r.old_title}</span> },
              { key: 'db_user', label: 'MySQL user' },
              { key: 'changed_at', label: 'When', render: (r) => fmtDate(r.changed_at) },
            ]} />
        </Panel>
      )}

      {editing && <ExamForm open exam={e} onClose={() => setEditing(false)}
        onSaved={() => { setEditing(false); toast('success', 'Exam saved — the audit trigger recorded the change'); refreshAll() }} />}
      {adding && <AddQuestion examId={e.exam_id} assigned={new Set((questions.data?.questions ?? []).map((q) => q.question_id))}
        onClose={() => setAdding(false)} onAdded={() => { toast('success', 'Question assigned'); refreshAll() }} />}
      <Modal open={confirmDelete} title="Delete this exam?" onClose={() => setConfirmDelete(false)}
        footer={<><Button variant="secondary" onClick={() => setConfirmDelete(false)}>Cancel</Button>
          <Button variant="danger" busy={remove.busy} onClick={() => remove.run()}>Delete exam</Button></>}>
        <p>The exam and its question assignments are removed in one transaction. Exams that students already attempted cannot be deleted — cancel them instead.</p>
        <div className="mt-3"><ErrorBanner error={remove.error} /></div>
      </Modal>
    </div>
  )
}

function InlineNumber({ value, onSave, min, step }: { value: number; onSave: (v: number) => void; min: number; step: number }) {
  const [v, setV] = useState(String(value))
  const changed = Number(v) !== Number(value)
  return (
    <span className="inline-flex items-center gap-1">
      <input type="number" value={v} min={min} step={step} onChange={(e) => setV(e.target.value)} aria-label="Value"
        className="w-16 rounded border border-rule px-1.5 py-0.5 text-right text-sm" />
      {changed && <button type="button" className="text-xs font-semibold text-teal" onClick={() => onSave(Number(v))}>Save</button>}
    </span>
  )
}

function AddQuestion({ examId, assigned, onClose, onAdded }:
  { examId: number; assigned: Set<number>; onClose: () => void; onAdded: () => void }) {
  const [search, setSearch] = useState('')
  const [type, setType] = useState('')
  const bank = useLoad(() => get<Page<Question>>(`/questions${qs({ search, question_type: type, page_size: 100 })}`), [search, type])
  const add = useAction(async (qid: number) => {
    await post(`/exams/${examId}/questions`, { question_id: qid })
    onAdded()
  })
  return (
    <Modal open title="Add questions from the bank" onClose={onClose} wide
      footer={<Button variant="secondary" onClick={onClose}>Done</Button>}>
      <div className="mb-3 grid gap-3 sm:grid-cols-[1fr_180px]">
        <Field label="Search"><Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Words in the question" /></Field>
        <Field label="Type"><Select value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">All types</option>
          {['MCQ', 'TRUE_FALSE', 'SHORT_ANSWER', 'LONG_ANSWER'].map((t) => <option key={t} value={t}>{t.replace('_', ' ').toLowerCase()}</option>)}
        </Select></Field>
      </div>
      <ErrorBanner error={bank.error ?? add.error} />
      <div className="max-h-96 overflow-y-auto">
        <ul className="divide-y divide-rule">
          {(bank.data?.items ?? []).map((q) => (
            <li key={q.question_id} className="flex items-center gap-3 py-2">
              <div className="flex-1 text-sm">
                <p>{q.question_text}</p>
                <p className="text-xs text-muted">#{q.question_id} · {q.question_type.replace('_', ' ').toLowerCase()} · {fmtNumber(q.marks)} marks · used in {q.usage_count} exam(s)</p>
              </div>
              {assigned.has(q.question_id) ? <Badge tone="PASS">added</Badge>
                : <Button variant="secondary" busy={add.busy} onClick={() => add.run(q.question_id)}>Add</Button>}
            </li>
          ))}
        </ul>
      </div>
    </Modal>
  )
}
