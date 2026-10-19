import { RefreshCw } from 'lucide-react'
import { Fragment, useState } from 'react'
import { SqlBlock } from '../components/data'
import { Badge, Button, ErrorBanner, PageHeader, Pagination, Panel, Select, Spinner, Stat } from '../components/ui'
import { get, qs } from '../lib/api'
import { cx, fmtDate, fmtMs, fmtNumber } from '../lib/format'
import { useLoad } from '../lib/hooks'
import type { Page } from '../lib/types'

interface LogRow {
  log_id: number; request_id: string; user_role: string; user_id: number | null; example_id: string | null
  category: string; execution_mode: string; target_db: string; statement_text: string; status: string
  rows_returned: number; rows_affected: number; duration_ms: number; error_code: number | null
  error_message: string | null; executed_at: string
}
interface HistoryPage extends Page<LogRow> { summary: { status: string; n: number; avg_ms: number }[] }

const MODES = ['EXAMPLE', 'CLEANUP', 'FREEFORM', 'EXPLAIN', 'PROCEDURE', 'REPORT', 'RESET']

export default function History() {
  const [status, setStatus] = useState('')
  const [mode, setMode] = useState('')
  const [page, setPage] = useState(1)
  const [open, setOpen] = useState<number | null>(null)
  const log = useLoad(() => get<HistoryPage>(`/sql/history${qs({ status, mode, page, page_size: 30 })}`), [status, mode, page])
  const summary = Object.fromEntries((log.data?.summary ?? []).map((s) => [s.status, s]))

  return (
    <div className="space-y-6">
      <PageHeader title="Execution history" description="Every DBMS-lab statement, report, plan and routine call is logged in sql_execution_log (metadata only — no passwords or tokens)."
        actions={<Button variant="secondary" onClick={log.reload}><RefreshCw className={cx('size-4', log.loading && 'animate-spin')} /> Refresh</Button>} />
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Succeeded" value={fmtNumber(summary.SUCCESS?.n ?? 0)} tone="teal" hint={`avg ${fmtMs(summary.SUCCESS?.avg_ms)}`} />
        <Stat label="Failed in MySQL" value={fmtNumber(summary.ERROR?.n ?? 0)} tone="danger" hint="includes expected constraint errors" />
        <Stat label="Rejected by policy" value={fmtNumber(summary.REJECTED?.n ?? 0)} tone="amber" hint="never reached MySQL" />
      </div>
      <ErrorBanner error={log.error} onRetry={log.reload} />
      <Panel flush title={`${(log.data?.total ?? 0).toLocaleString()} executions`} actions={
        <div className="flex gap-2">
          <Select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }} className="w-36" aria-label="Status">
            <option value="">All statuses</option>{['SUCCESS', 'ERROR', 'REJECTED'].map((s) => <option key={s} value={s}>{s.toLowerCase()}</option>)}
          </Select>
          <Select value={mode} onChange={(e) => { setMode(e.target.value); setPage(1) }} className="w-36" aria-label="Mode">
            <option value="">All modes</option>{MODES.map((m) => <option key={m} value={m}>{m.toLowerCase()}</option>)}
          </Select>
        </div>}>
        {log.loading && !log.data ? <Spinner /> : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <thead><tr className="border-b border-rule bg-paper">
                {['When', 'Status', 'Mode', 'Example', 'Database', 'Statement', 'Rows', 'Duration', 'By'].map((h) => <th key={h} className="px-3 py-2 font-semibold whitespace-nowrap">{h}</th>)}
              </tr></thead>
              <tbody>
                {(log.data?.items ?? []).map((r) => (
                  <Fragment key={r.log_id}>
                    <tr className="cursor-pointer border-b border-rule/70 hover:bg-paper" onClick={() => setOpen(open === r.log_id ? null : r.log_id)}>
                      <td className="px-3 py-2 whitespace-nowrap">{fmtDate(r.executed_at)}</td>
                      <td className="px-3 py-2"><Badge>{r.status}</Badge></td>
                      <td className="px-3 py-2 text-xs">{r.execution_mode.toLowerCase()}</td>
                      <td className="px-3 py-2 font-mono text-xs">{r.example_id ?? '—'}</td>
                      <td className="px-3 py-2 font-mono text-xs">{r.target_db}</td>
                      <td className="max-w-md truncate px-3 py-2 font-mono text-xs" title={r.statement_text}>{r.statement_text}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{r.rows_returned || r.rows_affected || 0}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{fmtMs(r.duration_ms)}</td>
                      <td className="px-3 py-2 text-xs">{r.user_role.toLowerCase()} #{r.user_id}</td>
                    </tr>
                    {open === r.log_id && (
                      <tr className="border-b border-rule bg-paper/60"><td colSpan={9} className="px-3 py-3">
                        <SqlBlock sql={r.statement_text} className="bg-surface" />
                        {r.error_message && <p className="mt-2 text-sm text-danger">MySQL error {r.error_code ?? ''}: {r.error_message}</p>}
                        <p className="mt-2 text-xs text-muted">request id {r.request_id} · category {r.category} · returned {r.rows_returned} · affected {r.rows_affected}</p>
                      </td></tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
            {log.data && <Pagination page={page} pageSize={30} total={log.data.total} onPage={setPage} />}
          </div>
        )}
      </Panel>
    </div>
  )
}
