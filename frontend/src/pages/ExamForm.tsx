import { useState } from 'react'
import { Button, ErrorBanner, Field, Input, Modal, Select } from '../components/ui'
import { post, put } from '../lib/api'
import { toLocalInput } from '../lib/format'
import { useAction } from '../lib/hooks'
import type { Exam, ExamStatus } from '../lib/types'

const STATUSES: ExamStatus[] = ['SCHEDULED', 'ACTIVE', 'COMPLETED', 'CANCELLED']

function defaults(exam?: Exam) {
  const now = new Date()
  const start = new Date(now.getTime() + 60 * 60 * 1000)
  const end = new Date(start.getTime() + 2 * 60 * 60 * 1000)
  const local = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
  return {
    title: exam?.title ?? '',
    subject: exam?.subject ?? '',
    exam_date: exam ? toLocalInput(exam.exam_date) : local(start),
    deadline: exam ? toLocalInput(exam.deadline) : local(end),
    duration_minutes: String(exam?.duration_minutes ?? 30),
    pass_percentage: String(exam?.pass_percentage ?? 40),
    status: (exam?.status ?? 'SCHEDULED') as ExamStatus,
  }
}

export default function ExamForm({ open, exam, onClose, onSaved }:
  { open: boolean; exam?: Exam; onClose: () => void; onSaved: (exam: Exam) => void }) {
  const [form, setForm] = useState(() => defaults(exam))
  const [errors, setErrors] = useState<Record<string, string>>({})
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value })

  const save = useAction(async () => {
    const body = { ...form, duration_minutes: Number(form.duration_minutes), pass_percentage: Number(form.pass_percentage) }
    const saved = exam ? await put<Exam>(`/exams/${exam.exam_id}`, body) : await post<Exam>('/exams', body)
    onSaved(saved)
  })

  function submit() {
    const errs: Record<string, string> = {}
    if (!form.title.trim()) errs.title = 'Enter a title'
    if (!form.subject.trim()) errs.subject = 'Enter a subject'
    const dur = Number(form.duration_minutes)
    if (!Number.isInteger(dur) || dur < 1 || dur > 600) errs.duration_minutes = '1 to 600 minutes'
    const pass = Number(form.pass_percentage)
    if (Number.isNaN(pass) || pass < 0 || pass > 100) errs.pass_percentage = '0 to 100'
    const start = new Date(form.exam_date).getTime()
    const end = new Date(form.deadline).getTime()
    if (!(end > start)) errs.deadline = 'Must be after the start'
    else if ((end - start) / 60000 < dur) errs.deadline = 'Window must be at least as long as the duration'
    setErrors(errs)
    if (!Object.keys(errs).length) void save.run()
  }

  return (
    <Modal open={open} title={exam ? 'Edit exam' : 'New exam'} onClose={onClose} wide
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button busy={save.busy} onClick={submit}>{exam ? 'Save changes' : 'Create exam'}</Button></>}>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <Field label="Title" error={errors.title}><Input value={form.title} onChange={set('title')} maxLength={150} /></Field>
        </div>
        <Field label="Subject" error={errors.subject}><Input value={form.subject} onChange={set('subject')} maxLength={100} /></Field>
        <Field label="Status"><Select value={form.status} onChange={set('status')}>
          {STATUSES.map((s) => <option key={s} value={s}>{s.toLowerCase()}</option>)}
        </Select></Field>
        <Field label="Window opens" error={errors.exam_date}><Input type="datetime-local" value={form.exam_date} onChange={set('exam_date')} /></Field>
        <Field label="Deadline (window closes)" error={errors.deadline}><Input type="datetime-local" value={form.deadline} onChange={set('deadline')} /></Field>
        <Field label="Duration (minutes)" error={errors.duration_minutes}><Input type="number" min={1} max={600} value={form.duration_minutes} onChange={set('duration_minutes')} /></Field>
        <Field label="Pass mark (%)" error={errors.pass_percentage}><Input type="number" min={0} max={100} step="0.5" value={form.pass_percentage} onChange={set('pass_percentage')} /></Field>
      </div>
      <p className="mt-3 text-xs text-muted">Total marks are calculated by a database trigger from the assigned questions.</p>
      <div className="mt-3"><ErrorBanner error={save.error} /></div>
    </Modal>
  )
}
