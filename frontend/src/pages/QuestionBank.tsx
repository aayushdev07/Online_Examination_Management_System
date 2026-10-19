import { Pencil, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { RecordTable } from '../components/data'
import {
  Badge, Button, ErrorBanner, Field, Input, Modal, PageHeader, Pagination, Panel, Select, Spinner, Textarea, useToast,
} from '../components/ui'
import { del, get, post, put, qs } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtNumber } from '../lib/format'
import { useAction, useLoad } from '../lib/hooks'
import type { Page, Question, QuestionType } from '../lib/types'

const TYPES: QuestionType[] = ['MCQ', 'TRUE_FALSE', 'SHORT_ANSWER', 'LONG_ANSWER']
const label = (t: string) => t.replace('_', ' ').toLowerCase()

export default function QuestionBank() {
  const toast = useToast()
  const { user } = useAuth()
  const [search, setSearch] = useState('')
  const [type, setType] = useState('')
  const [unassigned, setUnassigned] = useState(false)
  const [page, setPage] = useState(1)
  const [editing, setEditing] = useState<Question | 'new' | null>(null)
  const list = useLoad(() => get<Page<Question>>(`/questions${qs({ search, question_type: type, unassigned, page, page_size: 25 })}`),
    [search, type, unassigned, page])
  const remove = useAction(async (q: Question) => {
    await del(`/questions/${q.question_id}`)
    toast('success', `Question #${q.question_id} deleted`)
    list.reload()
  })

  return (
    <div className="space-y-6">
      <PageHeader title="Question bank" description="Reusable questions. A question assigned to an exam cannot be deleted (foreign key)."
        actions={<Button onClick={() => setEditing('new')}><Plus className="size-4" /> New question</Button>} />
      <ErrorBanner error={list.error ?? remove.error} onRetry={list.reload} />
      <Panel flush title={`${list.data?.total ?? 0} questions`} actions={
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <Input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1) }} placeholder="Search text" className="w-48" aria-label="Search questions" />
          <Select value={type} onChange={(e) => { setType(e.target.value); setPage(1) }} className="w-40" aria-label="Filter by type">
            <option value="">All types</option>
            {TYPES.map((t) => <option key={t} value={t}>{label(t)}</option>)}
          </Select>
          <label className="flex items-center gap-2"><input type="checkbox" checked={unassigned} onChange={(e) => { setUnassigned(e.target.checked); setPage(1) }} /> Unassigned only</label>
        </div>}>
        {list.loading && !list.data ? <Spinner /> : (
          <>
            <RecordTable<Question> rows={list.data?.items ?? []} rowKey={(r) => r.question_id}
              columns={[
                { key: 'question_id', label: 'ID', align: 'right' },
                { key: 'question_text', label: 'Question', render: (r) => (
                  <div className="max-w-xl">
                    <p>{r.question_text}</p>
                    {r.options && <p className="mt-1 text-xs text-muted">Options: {r.options.join(' / ')}</p>}
                    {r.correct_answer && <p className="text-xs text-teal">Key: {r.correct_answer}</p>}
                  </div>) },
                { key: 'question_type', label: 'Type', render: (r) => <Badge>{r.question_type}</Badge> },
                { key: 'marks', label: 'Marks', align: 'right', render: (r) => fmtNumber(r.marks) },
                { key: 'usage_count', label: 'Used in', align: 'right' },
                { key: 'actions', label: '', render: (r) => (user?.role === 'ADMIN' || r.created_by === user?.id) && (
                  <span className="flex gap-1">
                    <Button variant="ghost" onClick={() => setEditing(r)} aria-label={`Edit question ${r.question_id}`}><Pencil className="size-4" /></Button>
                    <Button variant="ghost" onClick={() => remove.run(r)} aria-label={`Delete question ${r.question_id}`}><Trash2 className="size-4" /></Button>
                  </span>) },
              ]} />
            {list.data && <Pagination page={page} pageSize={25} total={list.data.total} onPage={setPage} />}
          </>
        )}
      </Panel>
      {editing && <QuestionForm question={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)}
        onSaved={() => { setEditing(null); toast('success', 'Question saved'); list.reload() }} />}
    </div>
  )
}

export function QuestionForm({ question, onClose, onSaved }: { question?: Question; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({
    question_text: question?.question_text ?? '',
    question_type: (question?.question_type ?? 'MCQ') as QuestionType,
    options: question?.options?.join('\n') ?? '',
    marks: String(question?.marks ?? 2),
    correct_answer: question?.correct_answer ?? '',
  })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const options = form.options.split('\n').map((o) => o.trim()).filter(Boolean)

  const save = useAction(async () => {
    const body = {
      question_text: form.question_text, question_type: form.question_type, marks: Number(form.marks),
      options: form.question_type === 'MCQ' ? options : null,
      correct_answer: form.correct_answer.trim() || null,
    }
    if (question) await put(`/questions/${question.question_id}`, body)
    else await post('/questions', body)
    onSaved()
  })

  function submit() {
    const errs: Record<string, string> = {}
    if (!form.question_text.trim()) errs.question_text = 'Enter the question'
    const marks = Number(form.marks)
    if (!(marks > 0 && marks <= 1000)) errs.marks = 'Between 0 and 1000'
    if (form.question_type === 'MCQ') {
      if (options.length < 2) errs.options = 'At least two options, one per line'
      else if (!options.includes(form.correct_answer.trim())) errs.correct_answer = 'Pick one of the options'
    }
    if (form.question_type === 'SHORT_ANSWER' && !form.correct_answer.trim()) errs.correct_answer = 'Enter the expected answer'
    if (form.question_type === 'TRUE_FALSE' && !['TRUE', 'FALSE'].includes(form.correct_answer)) errs.correct_answer = 'Choose true or false'
    setErrors(errs)
    if (!Object.keys(errs).length) void save.run()
  }

  return (
    <Modal open title={question ? `Edit question #${question.question_id}` : 'New question'} onClose={onClose} wide
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button busy={save.busy} onClick={submit}>Save question</Button></>}>
      <div className="grid gap-4 sm:grid-cols-[1fr_160px_120px]">
        <div className="sm:col-span-3">
          <Field label="Question" error={errors.question_text}>
            <Textarea rows={3} value={form.question_text} onChange={(e) => setForm({ ...form, question_text: e.target.value })} />
          </Field>
        </div>
        <Field label="Type">
          <Select value={form.question_type} onChange={(e) => setForm({ ...form, question_type: e.target.value as QuestionType, correct_answer: '' })}>
            {TYPES.map((t) => <option key={t} value={t}>{label(t)}</option>)}
          </Select>
        </Field>
        <Field label="Marks" error={errors.marks}>
          <Input type="number" min={0.5} step={0.5} value={form.marks} onChange={(e) => setForm({ ...form, marks: e.target.value })} />
        </Field>
        <div />
        {form.question_type === 'MCQ' && (
          <div className="sm:col-span-3">
            <Field label="Options (one per line)" error={errors.options}>
              <Textarea rows={4} value={form.options} onChange={(e) => setForm({ ...form, options: e.target.value })} />
            </Field>
          </div>
        )}
        <div className="sm:col-span-3">
          {form.question_type === 'MCQ' && (
            <Field label="Correct option" error={errors.correct_answer}>
              <Select value={form.correct_answer} onChange={(e) => setForm({ ...form, correct_answer: e.target.value })}>
                <option value="">Choose…</option>
                {options.map((o) => <option key={o} value={o}>{o}</option>)}
              </Select>
            </Field>
          )}
          {form.question_type === 'TRUE_FALSE' && (
            <Field label="Correct answer" error={errors.correct_answer}>
              <Select value={form.correct_answer} onChange={(e) => setForm({ ...form, correct_answer: e.target.value })}>
                <option value="">Choose…</option><option value="TRUE">True</option><option value="FALSE">False</option>
              </Select>
            </Field>
          )}
          {(form.question_type === 'SHORT_ANSWER' || form.question_type === 'LONG_ANSWER') && (
            <Field label={form.question_type === 'SHORT_ANSWER' ? 'Expected answer (case-insensitive match)' : 'Model answer for graders (optional)'}
              error={errors.correct_answer}>
              <Input value={form.correct_answer} onChange={(e) => setForm({ ...form, correct_answer: e.target.value })} />
            </Field>
          )}
        </div>
      </div>
      <div className="mt-3"><ErrorBanner error={save.error} /></div>
    </Modal>
  )
}
