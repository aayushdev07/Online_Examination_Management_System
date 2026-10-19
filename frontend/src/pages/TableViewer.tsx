import { ArrowDown, ArrowUp, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { CellValue } from '../components/data'
import { Button, ErrorBanner, PageHeader, Pagination, Panel, Select, Spinner } from '../components/ui'
import { get, qs } from '../lib/api'
import { cx, fmtMs } from '../lib/format'
import { useLoad } from '../lib/hooks'
import type { Cell } from '../lib/types'
import { DatabasePicker, type Schema } from './SchemaExplorer'

interface Rows {
  database: string; table: string; columns: string[]; primary_key: string[]; rows: Cell[][]; total: number
  page: number; page_size: number; sort: string; direction: 'asc' | 'desc'; duration_ms: number; hidden_columns: string[]
}

export default function TableViewer() {
  const [params, setParams] = useSearchParams()
  const database = params.get('database') ?? 'main'
  const table = params.get('table') ?? 'exam'
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState<{ col: string | null; dir: 'asc' | 'desc' }>({ col: null, dir: 'asc' })
  const [pageSize, setPageSize] = useState(25)

  const schema = useLoad(() => get<Schema>(`/db/schema${qs({ database })}`), [database])
  const rows = useLoad(() => get<Rows>(`/db/tables/${encodeURIComponent(table)}/rows${qs({
    database, page, page_size: pageSize, sort: sort.col, direction: sort.dir })}`), [database, table, page, sort, pageSize])

  const select = (next: { database?: string; table?: string }) => {
    setParams({ database: next.database ?? database, table: next.table ?? table })
    setPage(1)
    setSort({ col: null, dir: 'asc' })
  }
  const toggleSort = (col: string) => {
    setSort((s) => ({ col, dir: s.col === col && s.dir === 'asc' ? 'desc' : 'asc' }))
    setPage(1)
  }
  const data = rows.data

  return (
    <div className="space-y-6">
      <PageHeader title="Table data" description="Browse any table or view. The application database is read through the SELECT-only account; password hashes are never sent to the browser."
        actions={<>
          <DatabasePicker value={database} onChange={(d) => select({ database: d, table: 'exam' })} />
          <Select value={table} onChange={(e) => select({ table: e.target.value })} className="w-60" aria-label="Table">
            {(schema.data?.tables ?? [{ name: table, type: 'BASE TABLE' }]).map((t) => (
              <option key={t.name} value={t.name}>{t.name}{t.type === 'VIEW' ? ' (view)' : ''}</option>
            ))}
          </Select>
          <Button variant="secondary" onClick={rows.reload}><RefreshCw className={cx('size-4', rows.loading && 'animate-spin')} /> Refresh</Button>
        </>} />
      <ErrorBanner error={rows.error ?? schema.error} onRetry={rows.reload} />
      <Panel flush title={<><span className="font-mono">{data?.database}.{table}</span>{data && <span className="ml-2 text-sm font-normal text-muted">query took {fmtMs(data.duration_ms)}</span>}</>}
        actions={<Select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1) }} className="w-28" aria-label="Rows per page">
          {[25, 50, 100, 200].map((n) => <option key={n} value={n}>{n} / page</option>)}
        </Select>}>
        {rows.loading && !data ? <Spinner /> : data && (
          <>
            <div className="max-h-[65vh] overflow-auto">
              <table className="w-full border-collapse text-left text-sm">
                <thead className="sticky top-0 bg-paper">
                  <tr>
                    {data.columns.map((c) => (
                      <th key={c} className="border-b border-rule px-3 py-2 whitespace-nowrap">
                        <button type="button" onClick={() => toggleSort(c)} className="inline-flex items-center gap-1 font-semibold">
                          {data.primary_key.includes(c) && <span className="rounded bg-bubble px-1 text-[10px]">PK</span>}
                          {c}
                          {data.sort === c && (data.direction === 'asc' ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />)}
                        </button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="tabular-nums">
                  {data.rows.map((r, i) => (
                    <tr key={i} className="border-b border-rule/70">
                      {r.map((v, j) => <td key={j} className="px-3 py-1.5 whitespace-nowrap"><CellValue value={v} /></td>)}
                    </tr>
                  ))}
                  {data.rows.length === 0 && <tr><td colSpan={data.columns.length} className="px-3 py-6 text-center text-muted">Empty table</td></tr>}
                </tbody>
              </table>
            </div>
            <Pagination page={page} pageSize={pageSize} total={data.total} onPage={setPage} />
          </>
        )}
      </Panel>
    </div>
  )
}
