export type Cell = string | number | boolean | null

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export type ExamStatus = 'SCHEDULED' | 'ACTIVE' | 'COMPLETED' | 'CANCELLED'
export type QuestionType = 'MCQ' | 'TRUE_FALSE' | 'SHORT_ANSWER' | 'LONG_ANSWER'

export interface Exam {
  exam_id: number
  title: string
  subject: string
  status: ExamStatus
  exam_date: string
  deadline: string
  duration_minutes: number
  total_marks: number
  pass_percentage: number
  results_released: boolean
  created_by_name: string
  created_by?: number
  question_count: number
  attempt_count?: number
  submitted_count?: number
  // student view
  attempt_id?: number | null
  attempt_status?: string | null
  started_at?: string | null
  submitted_at?: string | null
  percentage?: number | null
  result_status?: string | null
  can_start?: boolean
  can_resume?: boolean
}

export interface Question {
  question_id: number
  created_by: number
  question_text: string
  question_type: QuestionType
  options: string[] | null
  marks: number
  correct_answer: string | null
  created_at: string
  usage_count?: number
}

export interface AttemptQuestion {
  question_id: number
  question_order: number
  question_text: string
  question_type: QuestionType
  options: string[] | null
  marks: number
  selected_answer: string | null
  correct_answer?: string | null
  marks_obtained?: number | null
}

export interface ResultInfo {
  result_id: number
  marks_obtained: number
  total_marks: number
  percentage: number
  result_status: 'PASS' | 'FAIL'
  pass_percentage: number
  evaluated_at: string
}

export interface AttemptDetail {
  attempt_id: number
  status: 'IN_PROGRESS' | 'SUBMITTED' | 'EVALUATED'
  student: { student_id: number; student_name: string }
  exam: { exam_id: number; title: string; subject: string; duration_minutes: number; total_marks: number;
          deadline: string; results_released: boolean }
  started_at: string
  submitted_at: string | null
  ends_at: string
  server_now: string
  seconds_remaining: number
  answers_revealed: boolean
  questions: AttemptQuestion[]
  result: ResultInfo | null
}

export interface ResultSet {
  columns: string[]
  rows: Cell[][]
  row_count: number
  truncated: boolean
}

export interface LabParam {
  name: string
  label: string
  type: 'int' | 'decimal' | 'text'
  default: string | number
  min: number | null
  max: number | null
  max_length: number
}

export interface LabExample {
  id: string
  category: string
  title: string
  description: string
  explanation: string
  target: 'main' | 'lab'
  account: string
  destructive: boolean
  min_role: 'FACULTY' | 'ADMIN'
  has_cleanup: boolean
  allowed: boolean
  tags: string[]
  params: LabParam[]
  steps: { title: string; sql: string; role: string; conn: string; expect_error: boolean }[]
  cleanup: { title: string; sql: string }[]
}

export interface LabCategory {
  id: string
  title: string
  description: string
  count: number
}

export type StepStatus = 'success' | 'expected_error' | 'error' | 'skipped' | 'not_run' | 'unexpected_success'

export interface StepResult {
  title: string
  role: string
  sql: string
  connection: string
  account: string
  expect_error: boolean
  compare: string | null
  note: string
  repeat: number
  status: StepStatus
  result_sets?: ResultSet[]
  affected_rows?: number | null
  duration_ms?: number
  timings_ms?: number[] | null
  error?: { code: number | null; message: string }
}

export interface RunResult {
  example_id: string | null
  title: string
  category: string
  mode: string
  database: string
  account: string
  explanation: string
  params: Record<string, string | number>
  request_id: string
  status: 'success' | 'error'
  steps: StepResult[]
  total_duration_ms: number
  timing_comparison: null | {
    before_median_ms: number
    after_median_ms: number
    before_runs_ms: number[]
    after_runs_ms: number[]
    speedup: number | null
    verdict: string
  }
}

export interface Latency {
  samples: number
  avg_ms: number | null
  min_ms: number | null
  max_ms: number | null
  p50_ms: number | null
  p95_ms: number | null
  p99_ms: number | null
}
