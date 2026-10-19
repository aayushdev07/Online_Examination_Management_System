import { RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { RecordTable } from '../components/data'
import { Badge, Button, Callout, ErrorBanner, PageHeader, Panel, Spinner, Stat } from '../components/ui'
import { get } from '../lib/api'
import { cx, fmtBytes, fmtDate, fmtMs, fmtNumber } from '../lib/format'
import { useLoad } from '../lib/hooks'
import type { Latency } from '../lib/types'

interface Pool { size: number; checked_out: number; checked_in: number; overflow: number; max_overflow: number | null }
interface QueryRow { ts: string; source: string; duration_ms: number; statement: string; request_id: string; error: string | null }
interface Metrics {
  measured_since: string; uptime_seconds: number; excluded_routes: string[]
  api: { total_requests: number; status_classes: Record<string, number>
    window: { requests: number; success: number; client_errors: number; server_errors: number; success_rate: number | null }
    latency: Latency; routes: ({ route: string; count: number; errors: number } & Latency)[]
    recent: { ts: string; method: string; route: string; status: number; duration_ms: number; request_id: string }[] }
  db: { total_queries: number; total_failures: number; by_source: Record<string, number>; latency: Latency
    slow_queries: QueryRow[]; failed_queries: QueryRow[] }
  pools: Record<string, Pool>
  exam_activity: Record<string, number> | null
  sql_lab: { executions: number; errors: number; rejected: number; avg_ms: number; max_ms: number
    slowest: { log_id: number; execution_mode: string; statement: string; duration_ms: number; status: string; executed_at: string }[] }
}
interface DbMetrics { server_status: Record<string, string>; buffer_pool_hit_rate: number | null
  tables: { name: string; approx_rows: number; data_bytes: number; index_bytes: number }[] }

function pctValue(l: Latency, key: 'p50_ms' | 'p95_ms' | 'p99_ms', min: number) {
  const v = l[key]
  return v === null ? <span className="text-base text-muted">needs {min}+ samples</span> : fmtMs(v)
}

export default function Performance() {
  const [auto, setAuto] = useState(true)
  const metrics = useLoad(() => get<Metrics>('/metrics'))
  const db = useLoad(() => get<DbMetrics>('/db/metrics'))
  useEffect(() => {
    if (!auto) return
    const t = setInterval(() => { metrics.reload(); db.reload() }, 5000)
    return () => clearInterval(t)
  }, [auto, metrics.reload, db.reload])

  const m = metrics.data
  if (!m) return metrics.error ? <ErrorBanner error={metrics.error} onRetry={metrics.reload} /> : <Spinner />
  const pools = Object.entries(m.pools)

  return (
    <div className="space-y-6">
      <PageHeader title="Performance" description={<>Measured by this API process since {fmtDate(m.measured_since)} ({fmtNumber(m.uptime_seconds / 60, 1)} min). Values reset when the API restarts.</>}
        actions={<>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> Refresh every 5 s</label>
          <Button variant="secondary" onClick={() => { metrics.reload(); db.reload() }}><RefreshCw className={cx('size-4', metrics.loading && 'animate-spin')} /> Refresh</Button>
        </>} />
      <Callout>All numbers come from real requests and queries. Polling of the metrics endpoints themselves is excluded. To generate load, run <code>python scripts/load_test.py</code> from the backend folder.</Callout>

      <h2 className="text-lg font-bold">API</h2>
      <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-6">
        <Stat label="Requests" value={fmtNumber(m.api.total_requests)} hint={`window: last ${fmtNumber(m.api.window.requests)}`} />
        <Stat label="Success rate" value={m.api.window.success_rate === null ? '—' : `${fmtNumber(m.api.window.success_rate)}%`}
          tone="teal" hint={`${m.api.window.client_errors} 4xx · ${m.api.window.server_errors} 5xx`} />
        <Stat label="Average" value={fmtMs(m.api.latency.avg_ms)} />
        <Stat label="P50" value={pctValue(m.api.latency, 'p50_ms', 1)} />
        <Stat label="P95" value={pctValue(m.api.latency, 'p95_ms', 20)} />
        <Stat label="P99" value={pctValue(m.api.latency, 'p99_ms', 100)} />
      </div>

      <h2 className="text-lg font-bold">Database</h2>
      <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-6">
        <Stat label="Queries" value={fmtNumber(m.db.total_queries)} hint={Object.entries(m.db.by_source).map(([k, v]) => `${k} ${v}`).join(' · ')} />
        <Stat label="Failed queries" value={fmtNumber(m.db.total_failures)} tone={m.db.total_failures ? 'danger' : 'ink'} />
        <Stat label="Query P50" value={pctValue(m.db.latency, 'p50_ms', 1)} />
        <Stat label="Query P95" value={pctValue(m.db.latency, 'p95_ms', 20)} />
        <Stat label="Query P99" value={pctValue(m.db.latency, 'p99_ms', 100)} />
        <Stat label="Buffer pool hit rate" value={db.data?.buffer_pool_hit_rate == null ? '—' : `${fmtNumber(db.data.buffer_pool_hit_rate, 2)}%`}
          hint={`MySQL threads connected ${db.data?.server_status.Threads_connected ?? '—'}`} />
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel title="Connection pools">
          <div className="space-y-3">
            {pools.map(([name, p]) => {
              const capacity = p.size + (p.max_overflow ?? 0)
              return (
                <div key={name}>
                  <div className="flex justify-between text-sm"><span className="font-semibold">{name}</span>
                    <span className="text-muted tabular-nums">{p.checked_out} in use · {p.checked_in} idle · overflow {p.overflow} · capacity {capacity}</span></div>
                  <div className="mt-1 h-2 overflow-hidden rounded bg-rule">
                    <div className="h-full bg-teal" style={{ width: `${capacity ? Math.min(100, (p.checked_out / capacity) * 100) : 0}%` }} />
                  </div>
                </div>
              )
            })}
          </div>
        </Panel>
        <Panel title="Examination activity (live counts from attempt)">
          <div className="grid grid-cols-3 gap-3">
            {['IN_PROGRESS', 'SUBMITTED', 'EVALUATED'].map((s) => (
              <div key={s} className="text-center"><Badge>{s}</Badge><div className="mt-1 text-2xl font-bold tabular-nums">{fmtNumber(m.exam_activity?.[s] ?? 0)}</div></div>
            ))}
          </div>
          <p className="mt-4 text-sm text-muted">DBMS lab: {fmtNumber(m.sql_lab.executions)} logged executions · {fmtNumber(m.sql_lab.errors)} MySQL errors · {fmtNumber(m.sql_lab.rejected)} rejected · avg {fmtMs(m.sql_lab.avg_ms)}</p>
        </Panel>
      </div>

      <Panel flush title="Latency by endpoint">
        <RecordTable rows={m.api.routes} rowKey={(r) => r.route}
          columns={[
            { key: 'route', label: 'Endpoint', render: (r) => <span className="font-mono text-xs">{r.route}</span> },
            { key: 'count', label: 'Requests', align: 'right' },
            { key: 'errors', label: 'Errors', align: 'right' },
            { key: 'avg_ms', label: 'Avg', align: 'right', render: (r) => fmtMs(r.avg_ms) },
            { key: 'p50_ms', label: 'P50', align: 'right', render: (r) => fmtMs(r.p50_ms) },
            { key: 'p95_ms', label: 'P95', align: 'right', render: (r) => r.p95_ms === null ? '—' : fmtMs(r.p95_ms) },
            { key: 'max_ms', label: 'Max', align: 'right', render: (r) => fmtMs(r.max_ms) },
          ]} />
      </Panel>

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel flush title="Slow queries (application engines)">
          <QueryList rows={m.db.slow_queries} empty="No query crossed the slow-query threshold yet." />
        </Panel>
        <Panel flush title="Failed database operations">
          <QueryList rows={m.db.failed_queries} empty="No failed queries since the API started." />
        </Panel>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel flush title="Slowest DBMS-lab executions (sql_execution_log)">
          <RecordTable rows={m.sql_lab.slowest} rowKey={(r) => r.log_id}
            columns={[
              { key: 'duration_ms', label: 'Duration', align: 'right', render: (r) => fmtMs(r.duration_ms) },
              { key: 'execution_mode', label: 'Mode', render: (r) => r.execution_mode.toLowerCase() },
              { key: 'statement', label: 'Statement', render: (r) => <span className="font-mono text-xs">{r.statement}</span> },
              { key: 'status', label: 'Status', render: (r) => <Badge>{r.status}</Badge> },
            ]} />
        </Panel>
        <Panel flush title="Recent requests (correlation ids)">
          <RecordTable rows={m.api.recent.slice(0, 12)} rowKey={(r) => r.request_id}
            columns={[
              { key: 'method', label: 'Method' },
              { key: 'route', label: 'Route', render: (r) => <span className="font-mono text-xs">{r.route}</span> },
              { key: 'status', label: 'Status', align: 'right' },
              { key: 'duration_ms', label: 'Time', align: 'right', render: (r) => fmtMs(r.duration_ms) },
              { key: 'request_id', label: 'Request id', render: (r) => <span className="font-mono text-xs">{r.request_id.slice(0, 12)}</span> },
            ]} />
        </Panel>
      </div>

      {db.data && (
        <Panel flush title="Table sizes (information_schema, approximate row counts)">
          <RecordTable rows={db.data.tables} rowKey={(r) => r.name}
            columns={[
              { key: 'name', label: 'Table', render: (r) => <span className="font-mono">{r.name}</span> },
              { key: 'approx_rows', label: 'Rows (approx.)', align: 'right', render: (r) => fmtNumber(r.approx_rows) },
              { key: 'data_bytes', label: 'Data', align: 'right', render: (r) => fmtBytes(r.data_bytes) },
              { key: 'index_bytes', label: 'Indexes', align: 'right', render: (r) => fmtBytes(r.index_bytes) },
            ]} />
        </Panel>
      )}
    </div>
  )
}

function QueryList({ rows, empty }: { rows: QueryRow[]; empty: string }) {
  if (!rows.length) return <p className="p-4 text-sm text-muted">{empty}</p>
  return (
    <ul className="divide-y divide-rule">
      {rows.map((q, i) => (
        <li key={i} className="px-4 py-2 text-sm">
          <div className="flex justify-between gap-2 text-xs text-muted"><span>{q.source} · {fmtDate(q.ts)} · req {q.request_id.slice(0, 8)}</span><span className="font-semibold tabular-nums">{fmtMs(q.duration_ms)}</span></div>
          <p className="mt-0.5 truncate font-mono text-xs" title={q.statement}>{q.statement}</p>
          {q.error && <p className="text-xs text-danger">{q.error}</p>}
        </li>
      ))}
    </ul>
  )
}
