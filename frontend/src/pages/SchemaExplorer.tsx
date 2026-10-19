import { RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { RecordTable } from '../components/data'
import ErDiagram, { type ErColumn } from '../components/ErDiagram'
import { Badge, Button, ErrorBanner, PageHeader, Panel, Select, Spinner } from '../components/ui'
import { get, qs } from '../lib/api'
import { cx, fmtBytes, fmtNumber } from '../lib/format'
import { useLoad } from '../lib/hooks'

interface Column extends ErColumn { position: number; default_value: string | null; extra: string }
interface Constraint { name: string; type: string; columns: string | null; ref_table: string | null; ref_columns: string | null
  on_update: string | null; on_delete: string | null; check_clause: string | null }
interface Index { name: string; is_unique: boolean; index_type: string; columns: string; cardinality: number | null }
export interface TableMeta { name: string; type: string; engine: string | null; row_count: number | null; data_bytes: number
  index_bytes: number; auto_increment: number | null; columns: Column[]; constraints: Constraint[]; indexes: Index[] }
export interface Schema { database: string; tables: TableMeta[]
  relationships: { name: string; table: string; columns: string; ref_table: string; ref_columns: string; on_update: string; on_delete: string }[] }

export function DatabasePicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <Select value={value} onChange={(e) => onChange(e.target.value)} className="w-56" aria-label="Database">
      <option value="main">Application database</option>
      <option value="lab">Lab database (disposable)</option>
    </Select>
  )
}

export default function SchemaExplorer() {
  const [database, setDatabase] = useState('main')
  const [selected, setSelected] = useState<string | null>('exam')
  const schema = useLoad(() => get<Schema>(`/db/schema${qs({ database })}`), [database])
  const table = schema.data?.tables.find((t) => t.name === selected)

  return (
    <div className="space-y-6">
      <PageHeader title="Schema explorer"
        description="Read live from information_schema: tables, columns, keys, CHECK constraints and indexes. Click a table in the diagram."
        actions={<><DatabasePicker value={database} onChange={setDatabase} />
          <Button variant="secondary" onClick={schema.reload}><RefreshCw className={cx('size-4', schema.loading && 'animate-spin')} /> Refresh</Button></>} />
      <ErrorBanner error={schema.error} onRetry={schema.reload} />
      {schema.loading && !schema.data ? <Spinner /> : schema.data && (
        <>
          <Panel title={<>ER diagram · <span className="font-mono">{schema.data.database}</span></>}
            actions={<span className="text-xs text-muted">PK primary key · FK foreign key · UQ unique · * NOT NULL · crow's foot = many side</span>}>
            <div className="overflow-x-auto">
              <ErDiagram tables={schema.data.tables} relations={schema.data.relationships} selected={selected} onSelect={setSelected} />
            </div>
          </Panel>

          <div className="grid gap-6 xl:grid-cols-[300px_1fr]">
            <Panel flush title={`${schema.data.tables.length} tables and views`}>
              <ul className="divide-y divide-rule">
                {schema.data.tables.map((t) => (
                  <li key={t.name}>
                    <button type="button" onClick={() => setSelected(t.name)}
                      className={cx('flex w-full items-center justify-between gap-2 px-4 py-2 text-left text-sm hover:bg-paper',
                        selected === t.name && 'bg-bubble-soft font-semibold')}>
                      <span className="font-mono">{t.name}</span>
                      <span className="text-xs text-muted">{t.type === 'VIEW' ? 'view' : `${fmtNumber(t.row_count)} rows`}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </Panel>

            {table && (
              <div className="min-w-0 space-y-4">
                <Panel title={<span className="font-mono">{table.name}</span>} actions={
                  <span className="flex items-center gap-2 text-sm text-muted">
                    <Badge>{table.type === 'VIEW' ? 'view' : table.engine ?? ''}</Badge>
                    {table.type !== 'VIEW' && <>{fmtNumber(table.row_count)} rows (exact COUNT) · data {fmtBytes(table.data_bytes)} · indexes {fmtBytes(table.index_bytes)}</>}
                    <Link to={`/lab/tables?database=${database}&table=${table.name}`} className="font-semibold text-teal underline-offset-2 hover:underline">View data</Link>
                  </span>}>
                  <RecordTable<Column> rows={table.columns} rowKey={(c) => c.name}
                    columns={[
                      { key: 'position', label: '#', align: 'right' },
                      { key: 'name', label: 'Column', render: (c) => <span className="font-mono">{c.name}</span> },
                      { key: 'type', label: 'Type', render: (c) => <span className="font-mono text-xs">{c.type}</span> },
                      { key: 'nullable', label: 'Null', render: (c) => (c.nullable ? 'yes' : 'NOT NULL') },
                      { key: 'default_value', label: 'Default' },
                      { key: 'column_key', label: 'Key' },
                      { key: 'extra', label: 'Extra' },
                    ]} />
                </Panel>
                {table.type !== 'VIEW' && (
                  <>
                    <Panel flush title="Constraints">
                      <RecordTable<Constraint> rows={table.constraints} rowKey={(c) => c.name}
                        columns={[
                          { key: 'type', label: 'Type', render: (c) => <Badge>{c.type}</Badge> },
                          { key: 'name', label: 'Name', render: (c) => <span className="font-mono text-xs">{c.name}</span> },
                          { key: 'definition', label: 'Definition', render: (c) => (
                            <span className="font-mono text-xs">
                              {c.type === 'CHECK' ? c.check_clause
                                : c.type === 'FOREIGN KEY' ? `(${c.columns}) → ${c.ref_table}(${c.ref_columns}) on delete ${c.on_delete?.toLowerCase()}`
                                : `(${c.columns})`}
                            </span>) },
                        ]} />
                    </Panel>
                    <Panel flush title="Indexes">
                      <RecordTable<Index> rows={table.indexes} rowKey={(i) => i.name}
                        columns={[
                          { key: 'name', label: 'Index', render: (i) => <span className="font-mono text-xs">{i.name}</span> },
                          { key: 'columns', label: 'Columns', render: (i) => <span className="font-mono text-xs">{i.columns}</span> },
                          { key: 'is_unique', label: 'Unique', render: (i) => (i.is_unique ? 'yes' : 'no') },
                          { key: 'index_type', label: 'Structure' },
                          { key: 'cardinality', label: 'Cardinality', align: 'right', render: (i) => fmtNumber(i.cardinality) },
                        ]} />
                    </Panel>
                  </>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
