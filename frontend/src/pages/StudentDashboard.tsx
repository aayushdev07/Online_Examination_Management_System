import { CalendarClock, PlayCircle } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Badge, Button, Empty, ErrorBanner, PageHeader, Panel, Spinner, Stat, useToast } from '../components/ui'
import { get, post } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtDate, fmtNumber } from '../lib/format'
import { useAction, useLoad } from '../lib/hooks'
import type { Exam } from '../lib/types'

export default function StudentDashboard() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const toast = useToast()
  const exams = useLoad(() => get<Exam[]>('/exams'))
  const start = useAction(async (examId: number) => {
    const r = await post<{ attempt_id: number; resumed: boolean }>(`/exams/${examId}/attempts`)
    toast('success', r.resumed ? 'Attempt resumed' : 'Attempt started — the timer is running')
    navigate(`/attempts/${r.attempt_id}`)
  })

  if (exams.loading && !exams.data) return <Spinner />
  const list = exams.data ?? []
  const open = list.filter((e) => e.can_start || e.can_resume)
  const upcoming = list.filter((e) => !e.attempt_id && !e.can_start && (e.status === 'SCHEDULED' || e.status === 'ACTIVE'))
  const done = list.filter((e) => e.attempt_id && e.attempt_status !== 'IN_PROGRESS')
  const released = done.filter((e) => e.percentage !== null && e.percentage !== undefined)
  const avg = released.length ? released.reduce((s, e) => s + Number(e.percentage), 0) / released.length : null

  return (
    <div className="space-y-6">
      <PageHeader title={`Hello, ${user?.name.split(' ')[0]}`} description="Your examinations and results." />
      <ErrorBanner error={exams.error ?? start.error} onRetry={exams.reload} />

      <div className="grid gap-3 sm:grid-cols-4">
        <Stat label="Open now" value={open.length} tone={open.length ? 'teal' : 'ink'} />
        <Stat label="Upcoming" value={upcoming.length} />
        <Stat label="Submitted" value={done.length} />
        <Stat label="Average score" value={avg === null ? '—' : `${fmtNumber(avg, 1)}%`} hint="released results only" />
      </div>

      <Panel title="Open for you now" flush>
        {open.length === 0 ? (
          <div className="p-4"><Empty title="Nothing to attempt right now">Active exams appear here while their window is open.</Empty></div>
        ) : (
          <ul className="divide-y divide-rule">
            {open.map((e) => (
              <li key={e.exam_id} className="flex flex-wrap items-center justify-between gap-4 px-4 py-4">
                <div>
                  <p className="font-semibold">{e.title}</p>
                  <p className="text-sm text-muted">
                    {e.subject} · {e.question_count} questions · {fmtNumber(e.total_marks)} marks · {e.duration_minutes} min ·
                    closes {fmtDate(e.deadline)}
                  </p>
                </div>
                <Button busy={start.busy} onClick={() => start.run(e.exam_id)}>
                  <PlayCircle className="size-4" /> {e.can_resume ? 'Resume attempt' : 'Start exam'}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel title="Upcoming" flush>
          {upcoming.length === 0 ? <p className="p-4 text-sm text-muted">No upcoming exams.</p> : (
            <ul className="divide-y divide-rule">
              {upcoming.map((e) => (
                <li key={e.exam_id} className="flex items-center gap-3 px-4 py-3">
                  <CalendarClock className="size-4 text-muted" aria-hidden />
                  <div className="flex-1">
                    <p className="font-medium">{e.title}</p>
                    <p className="text-sm text-muted">{fmtDate(e.exam_date)} · {e.duration_minutes} min</p>
                  </div>
                  <Badge>{e.status}</Badge>
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <Panel title="My attempts" flush>
          {done.length === 0 ? <p className="p-4 text-sm text-muted">You have not submitted an exam yet.</p> : (
            <ul className="divide-y divide-rule">
              {done.map((e) => (
                <li key={e.exam_id}>
                  <button type="button" onClick={() => navigate(`/attempts/${e.attempt_id}`)}
                    className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-paper">
                    <div className="flex-1">
                      <p className="font-medium">{e.title}</p>
                      <p className="text-sm text-muted">Submitted {fmtDate(e.submitted_at)}</p>
                    </div>
                    {e.results_released && e.percentage !== null ? (
                      <span className="flex items-center gap-2">
                        <span className="font-semibold tabular-nums">{fmtNumber(e.percentage)}%</span>
                        <Badge>{e.result_status ?? ''}</Badge>
                      </span>
                    ) : <Badge tone="SUBMITTED">{e.attempt_status === 'SUBMITTED' ? 'grading' : 'result pending'}</Badge>}
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
