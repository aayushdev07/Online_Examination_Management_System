import { ArrowLeft, Check, Clock, Send, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  Badge, Button, Callout, ErrorBanner, Field, Input, Modal, PageHeader, Panel, Spinner, Stat, Textarea, useToast,
} from '../components/ui'
import { get, post, put } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cx, fmtDate, fmtDuration, fmtNumber } from '../lib/format'
import { useAction, useLoad } from '../lib/hooks'
import type { AttemptDetail, AttemptQuestion } from '../lib/types'

type Answers = Record<number, string>

function Bubble({ selected, label, letter, onClick, disabled, state }:
  { selected: boolean; label: string; letter: string; onClick?: () => void; disabled?: boolean;
    state?: 'correct' | 'wrong' | null }) {
  return (
    <button type="button" role="radio" aria-checked={selected} disabled={disabled} onClick={onClick}
      className={cx('flex w-full items-center gap-3 rounded-md border px-3 py-2.5 text-left text-sm',
        selected ? 'border-ink bg-bubble-soft' : 'border-rule bg-surface hover:border-ink/40',
        state === 'correct' && 'border-teal bg-teal-soft', state === 'wrong' && 'border-danger bg-danger-soft',
        disabled && 'cursor-default hover:border-rule')}>
      <span className={cx('flex size-6 shrink-0 items-center justify-center rounded-full border-[1.5px] text-xs font-bold',
        selected ? 'border-ink bg-bubble text-ink' : 'border-ink/30 text-muted')}>{letter}</span>
      <span className="flex-1">{label}</span>
      {state === 'correct' && <Check className="size-4 text-teal" aria-label="correct answer" />}
      {state === 'wrong' && <X className="size-4 text-danger" aria-label="your answer, incorrect" />}
    </button>
  )
}

function QuestionBody({ q, value, onChange, readOnly, reveal }:
  { q: AttemptQuestion; value: string; onChange: (v: string) => void; readOnly: boolean; reveal: boolean }) {
  const options = q.question_type === 'MCQ' ? q.options ?? [] : q.question_type === 'TRUE_FALSE' ? ['TRUE', 'FALSE'] : null
  if (options) {
    return (
      <div role="radiogroup" className="grid gap-2 sm:grid-cols-2">
        {options.map((opt, i) => {
          const isCorrect = reveal && q.correct_answer?.toUpperCase() === opt.toUpperCase()
          const isWrong = reveal && value === opt && !isCorrect
          return (
            <Bubble key={opt} letter={String.fromCharCode(65 + i)} label={opt === 'TRUE' ? 'True' : opt === 'FALSE' ? 'False' : opt}
              selected={value === opt} disabled={readOnly} onClick={() => onChange(value === opt ? '' : opt)}
              state={isCorrect ? 'correct' : isWrong ? 'wrong' : null} />
          )
        })}
      </div>
    )
  }
  if (q.question_type === 'SHORT_ANSWER') {
    return (
      <div className="space-y-2">
        <Input value={value} onChange={(e) => onChange(e.target.value)} readOnly={readOnly} maxLength={500}
          placeholder={readOnly ? '(no answer)' : 'Type a short answer'} aria-label="Your answer" />
        {reveal && q.correct_answer && <p className="text-sm text-teal">Expected answer: {q.correct_answer}</p>}
      </div>
    )
  }
  return (
    <div className="space-y-2">
      <Textarea rows={6} value={value} onChange={(e) => onChange(e.target.value)} readOnly={readOnly} maxLength={5000}
        placeholder={readOnly ? '(no answer)' : 'Write your answer'} aria-label="Your answer" />
      {!readOnly && <p className="text-xs text-muted">{value.length}/5000 characters · graded by faculty</p>}
      {reveal && q.correct_answer && <p className="text-sm text-teal">Model answer: {q.correct_answer}</p>}
    </div>
  )
}

export default function AttemptPage() {
  const { attemptId } = useParams()
  const { user } = useAuth()
  const toast = useToast()
  const attempt = useLoad(() => get<AttemptDetail>(`/attempts/${attemptId}`), [attemptId])
  const [answers, setAnswers] = useState<Answers>({})
  const [dirty, setDirty] = useState<Set<number>>(new Set())
  const [current, setCurrent] = useState(0)
  const [endAt, setEndAt] = useState<number | null>(null)   // client clock deadline derived from the server's remaining time
  const [now, setNow] = useState(() => Date.now())
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [savedAt, setSavedAt] = useState<string | null>(null)
  const [grades, setGrades] = useState<Record<number, string>>({})
  const autoSubmitted = useRef(false)

  const data = attempt.data
  const isStudent = user?.role === 'STUDENT'
  const live = isStudent && data?.status === 'IN_PROGRESS'
  const remaining = endAt === null ? null : Math.max(0, Math.ceil((endAt - now) / 1000))

  useEffect(() => {
    if (!data) return
    setAnswers(Object.fromEntries(data.questions.map((q) => [q.question_id, q.selected_answer ?? ''])))
    setDirty(new Set())
    setEndAt(Date.now() + data.seconds_remaining * 1000)
    setNow(Date.now())
  }, [data])

  // countdown driven by the server's remaining time
  useEffect(() => {
    if (!live) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [live])

  const save = useAction(async (ids?: number[]) => {
    const list = ids ?? [...dirty]
    if (!list.length) return
    const res = await put<{ saved: number; saved_at: string }>(`/attempts/${attemptId}/answers`, {
      answers: list.map((id) => ({ question_id: id, selected_answer: answers[id] || null })),
    })
    setDirty((d) => new Set([...d].filter((x) => !list.includes(x))))
    setSavedAt(res.saved_at)
  })

  const submit = useAction(async () => {
    if (dirty.size && (remaining ?? 0) > 0) await save.run()
    const res = await post<{ status: string; pending_manual_grading: number }>(`/attempts/${attemptId}/submit`)
    setConfirmOpen(false)
    toast('success', res.status === 'EVALUATED' ? 'Submitted and graded' : 'Submitted — waiting for manual grading')
    attempt.reload()
  })

  const grade = useAction(async () => {
    const list = Object.entries(grades).filter(([, v]) => v !== '')
    if (!list.length) return
    const res = await post<{ status: string; ungraded_remaining: number }>(`/attempts/${attemptId}/grade`, {
      grades: list.map(([id, v]) => ({ question_id: Number(id), marks_obtained: Number(v) })),
    })
    toast('success', res.status === 'EVALUATED' ? 'Grades saved — result created' : `Grades saved, ${res.ungraded_remaining} left`)
    setGrades({})
    attempt.reload()
  })

  // autosave 1.5 s after the last change
  useEffect(() => {
    if (!live || dirty.size === 0) return
    const t = setTimeout(() => void save.run(), 1500)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [answers, live])

  // auto-submit when the time is up
  useEffect(() => {
    if (live && remaining === 0 && !autoSubmitted.current) {
      autoSubmitted.current = true
      toast('error', 'Time is up — submitting your attempt')
      void submit.run()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remaining, live])

  const setAnswer = useCallback((id: number, v: string) => {
    setAnswers((a) => ({ ...a, [id]: v }))
    setDirty((d) => new Set(d).add(id))
  }, [])

  const answeredCount = useMemo(() => Object.values(answers).filter((v) => v.trim()).length, [answers])

  if (attempt.loading && !data) return <Spinner />
  if (!data) return <ErrorBanner error={attempt.error} onRetry={attempt.reload} />

  const q = data.questions[current]
  const back = isStudent ? '/' : `/exams/${data.exam.exam_id}`
  const ungraded = data.questions.filter((x) => x.marks_obtained === null || x.marks_obtained === undefined)

  return (
    <div className="space-y-6">
      <Link to={back} className="inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
        <ArrowLeft className="size-4" /> {isStudent ? 'Dashboard' : 'Back to exam'}
      </Link>
      <PageHeader title={data.exam.title}
        description={<>{data.exam.subject} · {data.student.student_name} · started {fmtDate(data.started_at)}</>}
        actions={<Badge>{data.status}</Badge>} />
      <ErrorBanner error={attempt.error ?? save.error ?? submit.error ?? grade.error} />

      {live && (
        <div className={cx('sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-3',
          (remaining ?? 0) < 120 ? 'border-danger/40 bg-danger-soft' : 'border-rule bg-surface')}>
          <div className="flex items-center gap-2 font-semibold tabular-nums" aria-live="polite">
            <Clock className="size-4" /> {fmtDuration(remaining ?? 0)} left
          </div>
          <span className="text-sm text-muted">
            {answeredCount}/{data.questions.length} answered ·{' '}
            {save.busy ? 'saving…' : dirty.size ? `${dirty.size} unsaved` : savedAt ? `saved ${fmtDate(savedAt)}` : 'nothing to save'}
          </span>
          <div className="flex gap-2">
            <Button variant="secondary" busy={save.busy} disabled={!dirty.size} onClick={() => save.run()}>Save</Button>
            <Button onClick={() => setConfirmOpen(true)}><Send className="size-4" /> Submit exam</Button>
          </div>
        </div>
      )}

      {data.result && (
        <div className="grid gap-3 sm:grid-cols-4">
          <Stat label="Marks" value={`${fmtNumber(data.result.marks_obtained)} / ${fmtNumber(data.result.total_marks)}`} />
          <Stat label="Percentage" value={`${fmtNumber(data.result.percentage)}%`} />
          <Stat label="Result" value={data.result.result_status} tone={data.result.result_status === 'PASS' ? 'teal' : 'danger'}
            hint={`pass mark ${fmtNumber(data.result.pass_percentage)}%`} />
          <Stat label="Evaluated" value={<span className="text-base">{fmtDate(data.result.evaluated_at)}</span>} />
        </div>
      )}
      {isStudent && data.status !== 'IN_PROGRESS' && !data.result && (
        <Callout tone="info">
          {data.status === 'SUBMITTED'
            ? 'Your attempt is submitted. Some answers need manual grading by faculty.'
            : 'Your attempt is graded. Marks and correct answers appear here once the faculty releases results.'}
        </Callout>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_220px]">
        <Panel title={<>Question {q.question_order} <span className="font-normal text-muted">· {fmtNumber(q.marks)} marks · {q.question_type.replace('_', ' ').toLowerCase()}</span></>}>
          <p className="mb-4 text-base whitespace-pre-line">{q.question_text}</p>
          <QuestionBody q={q} value={answers[q.question_id] ?? ''} onChange={(v) => setAnswer(q.question_id, v)}
            readOnly={!live} reveal={data.answers_revealed} />
          {data.answers_revealed && q.marks_obtained !== undefined && (
            <p className="mt-3 text-sm font-semibold">
              Marks awarded: {q.marks_obtained === null ? 'not graded yet' : `${fmtNumber(q.marks_obtained)} / ${fmtNumber(q.marks)}`}
            </p>
          )}
          <div className="mt-6 flex justify-between">
            <Button variant="secondary" disabled={current === 0} onClick={() => setCurrent(current - 1)}>Previous</Button>
            <Button variant="secondary" disabled={current === data.questions.length - 1} onClick={() => setCurrent(current + 1)}>Next</Button>
          </div>
        </Panel>

        <Panel title="Answer sheet">
          <div className="grid grid-cols-5 gap-2">
            {data.questions.map((x, i) => {
              const answered = !!answers[x.question_id]?.trim()
              return (
                <button key={x.question_id} type="button" onClick={() => setCurrent(i)}
                  aria-label={`Question ${x.question_order}${answered ? ', answered' : ''}`}
                  className={cx('flex size-9 items-center justify-center rounded-full border-[1.5px] text-xs font-bold',
                    answered ? 'border-ink bg-bubble' : 'border-ink/30 text-muted',
                    i === current && 'ring-2 ring-teal ring-offset-2')}>
                  {x.question_order}
                </button>
              )
            })}
          </div>
          <p className="mt-3 text-xs text-muted">Filled bubbles are answered questions.</p>
        </Panel>
      </div>

      {!isStudent && data.status === 'SUBMITTED' && (
        <Panel title="Manual grading" actions={<Button busy={grade.busy} onClick={() => grade.run()}>Save grades</Button>}>
          {ungraded.length === 0 ? <p className="text-sm text-muted">Every answer has marks.</p> : (
            <div className="space-y-4">
              <p className="text-sm text-muted">When the last answer is graded, <code>sp_finalize_attempt</code> creates the result in the same transaction.</p>
              {ungraded.map((x) => (
                <div key={x.question_id} className="rounded-md border border-rule p-3">
                  <p className="font-medium">Q{x.question_order}. {x.question_text}</p>
                  <p className="mt-2 rounded bg-paper p-2 text-sm whitespace-pre-line">{x.selected_answer || '(no answer)'}</p>
                  {x.correct_answer && <p className="mt-1 text-xs text-teal">Model answer: {x.correct_answer}</p>}
                  <div className="mt-2 max-w-48">
                    <Field label={`Marks (0–${fmtNumber(x.marks)})`}>
                      <Input type="number" min={0} max={x.marks} step="0.5" value={grades[x.question_id] ?? ''}
                        onChange={(e) => setGrades({ ...grades, [x.question_id]: e.target.value })} />
                    </Field>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>
      )}

      <Modal open={confirmOpen} title="Submit this exam?" onClose={() => setConfirmOpen(false)}
        footer={<>
          <Button variant="secondary" onClick={() => setConfirmOpen(false)}>Keep working</Button>
          <Button busy={submit.busy} onClick={() => submit.run()}>Submit exam</Button>
        </>}>
        <p>You answered {answeredCount} of {data.questions.length} questions. After submitting you cannot change any answer.</p>
        {answeredCount < data.questions.length && (
          <p className="mt-2 text-sm text-amber">Unanswered questions score 0.</p>
        )}
      </Modal>
    </div>
  )
}
