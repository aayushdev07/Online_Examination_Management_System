import { RotateCcw } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { RecordTable } from '../components/data'
import { Badge, Button, Callout, ErrorBanner, Modal, PageHeader, Panel, Spinner, Stat, useToast } from '../components/ui'
import { get, post, qs } from '../lib/api'
import { fmtMs, fmtNumber } from '../lib/format'
import { useAction, useLoad } from '../lib/hooks'
import type { Page } from '../lib/types'
import { PerformanceTable, type PerfRow } from './FacultyDashboard'

interface Probe { status: 'up' | 'down'; latency_ms: number; version?: string; error?: { message: string } }
interface DbMetrics { connectivity: Record<string, Probe>; server_status: Record<string, string>; buffer_pool_hit_rate: number | null }
interface Health { status: string; database: Probe }
interface SqlConfig { main_database: string; lab_database: string; accounts: Record<string, string>; freeform_enabled: boolean }

export default function AdminDashboard() {
  const toast = useToast()
  const [confirmReset, setConfirmReset] = useState(false)
  const health = useLoad(() => fetch('/api/health').then((r) => r.json() as Promise<Health>))
  const db = useLoad(() => get<DbMetrics>('/db/metrics'))
  const cfg = useLoad(() => get<SqlConfig>('/sql/config'))
  const students = useLoad(() => get<Page<unknown>>(`/students${qs({ page_size: 1 })}`))
  const staff = useLoad(() => get<unknown[]>('/staff'))
  const perf = useLoad(() => get<PerfRow[]>('/results/performance'))
  const reset = useAction(async () => {
    const r = await post<{ duration_ms: number; bulk_students: number }>('/sql/lab/reset')
    setConfirmReset(false)
    toast('success', `Lab database rebuilt in ${(r.duration_ms / 1000).toFixed(1)} s`)
  })

  const probes = db.data?.connectivity ?? {}
  return (
    <div className="space-y-6">
      <PageHeader title="Administration" description="System health, accounts and the DBMS lab environment."
        actions={<Button variant="secondary" onClick={() => { health.reload(); db.reload() }}>Refresh</Button>} />
      <ErrorBanner error={db.error ?? cfg.error ?? reset.error} />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="API + database" value={health.data ? <Badge>{health.data.database.status}</Badge> : '…'}
          hint={health.data ? `round trip ${fmtMs(health.data.database.latency_ms)} · MySQL ${health.data.database.version ?? '?'}` : undefined} />
        <Stat label="Students" value={fmtNumber(students.data?.total)} hint={<Link className="underline" to="/admin/users">Manage users</Link>} />
        <Stat label="Staff accounts" value={fmtNumber(staff.data?.length)} />
        <Stat label="Buffer pool hit rate" value={db.data?.buffer_pool_hit_rate == null ? '—' : `${fmtNumber(db.data.buffer_pool_hit_rate, 2)}%`}
          hint={`MySQL uptime ${fmtNumber(Number(db.data?.server_status.Uptime ?? 0) / 3600, 1)} h`} />
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel flush title="Database accounts used by the API">
          {db.loading && !db.data ? <Spinner /> : (
            <RecordTable rows={Object.entries(probes).map(([key, p]) => ({ key, account: cfg.data?.accounts[key] ?? (key === 'app' ? 'oems_app' : key), ...p }))}
              columns={[
                { key: 'key', label: 'Engine' },
                { key: 'account', label: 'MySQL account' },
                { key: 'status', label: 'Status', render: (r) => <Badge>{r.status}</Badge> },
                { key: 'latency_ms', label: 'Round trip', align: 'right', render: (r) => fmtMs(r.latency_ms) },
              ]} />
          )}
        </Panel>
        <Panel title="DBMS lab environment" actions={<Button variant="danger" onClick={() => setConfirmReset(true)}><RotateCcw className="size-4" /> Reset lab database</Button>}>
          {cfg.data && (
            <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm">
              <dt className="text-muted">Application database</dt><dd className="font-mono">{cfg.data.main_database}</dd>
              <dt className="text-muted">Lab database</dt><dd className="font-mono">{cfg.data.lab_database}</dd>
              <dt className="text-muted">Free-form SQL</dt><dd>{cfg.data.freeform_enabled ? <Badge tone="PASS">enabled (admins)</Badge> : <Badge>disabled</Badge>}</dd>
            </dl>
          )}
          <p className="mt-4 text-sm text-muted">Reset drops the lab database and rebuilds it from database/*.sql with fresh synthetic data, using only the lab account's privileges.</p>
        </Panel>
      </div>

      <Panel flush title="Performance by exam">{perf.data ? <PerformanceTable rows={perf.data} /> : <Spinner />}</Panel>

      <Modal open={confirmReset} title="Reset the lab database?" onClose={() => setConfirmReset(false)}
        footer={<><Button variant="secondary" onClick={() => setConfirmReset(false)}>Cancel</Button>
          <Button variant="danger" busy={reset.busy} onClick={() => reset.run()}>Reset lab database</Button></>}>
        <Callout tone="warning">Everything changed in the lab database by demonstrations is discarded. The application database is not touched.</Callout>
        <div className="mt-3"><ErrorBanner error={reset.error} /></div>
      </Modal>
    </div>
  )
}
