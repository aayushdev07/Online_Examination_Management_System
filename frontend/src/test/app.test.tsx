import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { diffRows, ResultGrid } from '../components/data'
import { ErrorBanner, ToastProvider } from '../components/ui'
import { api, ApiError } from '../lib/api'
import { AuthProvider } from '../lib/auth'
import type { RunResult } from '../lib/types'
import Login from '../pages/Login'
import { RunView } from '../pages/SqlCenter'
import StudentDashboard from '../pages/StudentDashboard'

function mockFetch(handler: (url: string, init?: RequestInit) => { status: number; body: unknown }) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const { status, body } = handler(url, init)
    return new Response(body === undefined ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

function wrap(ui: React.ReactNode) {
  return render(<MemoryRouter><AuthProvider><ToastProvider>{ui}</ToastProvider></AuthProvider></MemoryRouter>)
}

afterEach(() => vi.unstubAllGlobals())

describe('api client', () => {
  it('turns the backend error envelope into an ApiError', async () => {
    mockFetch(() => ({ status: 409, body: { error: { code: 'duplicate_value', message: "Duplicate entry 'x' for key 'uq_student_email'",
      details: { mysql_errno: 1062 }, request_id: 'abc123' } } }))
    const err = await api('/students').catch((e: ApiError) => e) as ApiError
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(409)
    expect(err.code).toBe('duplicate_value')
    expect(err.requestId).toBe('abc123')
  })

  it('reports an unreachable backend clearly', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    const err = await api('/health').catch((e: ApiError) => e) as ApiError
    expect(err.code).toBe('network_error')
    expect(err.message).toMatch(/not reachable/)
  })

  it('sends the bearer token and JSON body', async () => {
    sessionStorage.setItem('oems.token', 'tok')
    const fn = mockFetch(() => ({ status: 200, body: { ok: true } }))
    await api('/exams', { method: 'POST', body: { title: 'x' } })
    const [url, init] = fn.mock.calls[0]
    expect(url).toBe('/api/exams')
    expect((init!.headers as Record<string, string>).Authorization).toBe('Bearer tok')
    expect(init!.body).toBe('{"title":"x"}')
  })
})

describe('login form', () => {
  it('validates required fields before calling the API', async () => {
    const fn = mockFetch(() => ({ status: 200, body: {} }))
    wrap(<Login />)
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(screen.getByText('Enter your username')).toBeInTheDocument()
    expect(screen.getByText('Enter your password')).toBeInTheDocument()
    expect(fn).not.toHaveBeenCalled()
  })

  it('enforces the password rule when registering', async () => {
    mockFetch(() => ({ status: 200, body: {} }))
    wrap(<Login />)
    await userEvent.click(screen.getByRole('button', { name: 'Create an account' }))
    await userEvent.type(screen.getByLabelText('Full name'), 'Test User')
    await userEvent.type(screen.getByLabelText('E-mail'), 'test@example.com')
    await userEvent.type(screen.getByLabelText('Username'), 'test_user')
    await userEvent.type(screen.getByLabelText(/^Password/), 'short')
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(screen.getByText('At least 8 characters with a letter and a digit')).toBeInTheDocument()
  })

  it('shows the server error for wrong credentials', async () => {
    mockFetch(() => ({ status: 401, body: { error: { code: 'invalid_credentials', message: 'Incorrect username or password.' } } }))
    wrap(<Login />)
    await userEvent.type(screen.getByLabelText('Username or e-mail'), 'admin')
    await userEvent.type(screen.getByLabelText('Password'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect username or password.')
  })
})

describe('data rendering', () => {
  it('renders NULL values and highlights new rows', () => {
    const before = { columns: ['id', 'title'], rows: [[1, 'A']], row_count: 1, truncated: false }
    const after = { columns: ['id', 'title'], rows: [[1, 'A'], [2, null]], row_count: 2, truncated: false }
    const changed = diffRows(before, after)
    expect(changed.size).toBe(1)
    const { container } = render(<ResultGrid result={after} highlight={changed} />)
    expect(screen.getByText('NULL')).toBeInTheDocument()
    expect(container.querySelectorAll('tr.bg-bubble-soft')).toHaveLength(1)
    expect(screen.getByText('2 rows')).toBeInTheDocument()
  })

  it('shows MySQL error numbers in the error banner', () => {
    render(<ErrorBanner error={new ApiError(409, 'row_referenced', 'Cannot delete a parent row', { mysql_errno: 1451 })} />)
    expect(screen.getByRole('alert')).toHaveTextContent('MySQL error 1451')
  })

  it('renders an execution result with affected rows and expected errors', () => {
    const result: RunResult = {
      example_id: 'x', title: 'Demo', category: 'DML', mode: 'EXAMPLE', database: 'oems_lab', account: 'oems_lab',
      explanation: '', params: {}, request_id: 'req12345', status: 'success', total_duration_ms: 3, timing_comparison: null,
      steps: [
        { title: 'Update', role: 'main', sql: 'UPDATE exam SET title = 1', connection: 'lab', account: 'oems_lab',
          expect_error: false, compare: null, note: '', repeat: 1, status: 'success', affected_rows: 1, duration_ms: 1.2, result_sets: [] },
        { title: 'Bad', role: 'main', sql: 'UPDATE exam SET duration_minutes = 0', connection: 'lab', account: 'oems_lab',
          expect_error: true, compare: null, note: '', repeat: 1, status: 'expected_error', duration_ms: 0.5,
          error: { code: 3819, message: "Check constraint 'chk_exam_duration' is violated." } },
      ],
    }
    render(<RunView result={result} />)
    expect(screen.getByText(/1<\/strong>|row affected/)).toBeInTheDocument()
    expect(screen.getByText('rejected as expected')).toBeInTheDocument()
    expect(screen.getByText(/chk_exam_duration/)).toBeInTheDocument()
  })
})

describe('loading and error states', () => {
  it('shows a spinner, then the exams from the API', async () => {
    sessionStorage.setItem('oems.user', JSON.stringify({ id: 1, role: 'STUDENT', name: 'Aarav Shah', username: 'a', email: 'a@x.y' }))
    mockFetch(() => ({ status: 200, body: [{ exam_id: 5, title: 'DBMS Unit Test 2', subject: 'DBMS', status: 'ACTIVE',
      exam_date: '2026-10-19 09:00:00', deadline: '2026-11-19 23:59:00', duration_minutes: 30, total_marks: 17,
      pass_percentage: 40, results_released: false, created_by_name: 'P', question_count: 8, attempt_id: null,
      can_start: true, can_resume: false }] }))
    wrap(<StudentDashboard />)
    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(await screen.findByText('DBMS Unit Test 2')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Start exam/ })).toBeInTheDocument()
  })

  it('shows the error banner when the API fails', async () => {
    sessionStorage.setItem('oems.user', JSON.stringify({ id: 1, role: 'STUDENT', name: 'Aarav Shah', username: 'a', email: 'a@x.y' }))
    mockFetch(() => ({ status: 503, body: { error: { code: 'database_unavailable', message: 'The database is not reachable right now.' } } }))
    wrap(<StudentDashboard />)
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('The database is not reachable right now.'))
  })
})
