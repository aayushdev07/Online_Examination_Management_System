import type { ReactNode } from 'react'
import { cx } from '../lib/format'
import type { Cell, ResultSet } from '../lib/types'

// --------------------------------------------------------------------------- SQL display
const KEYWORDS = new Set((
  'SELECT FROM WHERE AND OR NOT NULL IS IN EXISTS JOIN INNER LEFT RIGHT CROSS ON AS GROUP BY ORDER HAVING LIMIT ' +
  'OFFSET DISTINCT INSERT INTO VALUES UPDATE SET DELETE CREATE TABLE VIEW INDEX TRIGGER PROCEDURE FUNCTION DROP ' +
  'ALTER RENAME TO TRUNCATE ADD COLUMN MODIFY CONSTRAINT PRIMARY KEY FOREIGN REFERENCES UNIQUE CHECK DEFAULT ' +
  'START TRANSACTION COMMIT ROLLBACK SAVEPOINT GRANT REVOKE USER IDENTIFIED SHOW GRANTS EXPLAIN ANALYZE CALL ' +
  'BEGIN END RETURN RETURNS IF ELSE THEN CASE WHEN DESC ASC WITH UNION ALL BETWEEN LIKE DESCRIBE REPLACE ' +
  'AFTER BEFORE FOR EACH ROW DECLARE DETERMINISTIC READS SQL DATA ENGINE IGNORE INTERVAL OUT OR COUNT SUM AVG MIN MAX'
).split(' '))

export function SqlBlock({ sql, className, wrap }: { sql: string; className?: string; wrap?: boolean }) {
  const parts: ReactNode[] = []
  const re = /('(?:\\.|''|[^'\\])*'|`[^`]*`|--[^\n]*|\b[A-Za-z_]+\b|\s+|.)/g
  let m: RegExpExecArray | null
  let i = 0
  while ((m = re.exec(sql))) {
    const tok = m[0]
    if (tok.startsWith("'")) parts.push(<span key={i++} className="text-teal">{tok}</span>)
    else if (tok.startsWith('--')) parts.push(<span key={i++} className="text-muted italic">{tok}</span>)
    else if (KEYWORDS.has(tok.toUpperCase())) parts.push(<span key={i++} className="font-semibold text-ink">{tok}</span>)
    else parts.push(tok)
  }
  return (
    <pre className={cx('sql overflow-x-auto rounded-md border border-rule bg-paper px-3 py-2 leading-relaxed text-ink-soft',
      wrap && 'break-words whitespace-pre-wrap', className)}><code>{parts}</code></pre>
  )
}

// --------------------------------------------------------------------------- cells
export function CellValue({ value }: { value: Cell }) {
  if (value === null) return <span className="text-muted/70 italic">NULL</span>
  if (typeof value === 'boolean') return <>{value ? 'true' : 'false'}</>
  const text = String(value)
  if (text.includes('\n')) return <span className="font-mono text-xs whitespace-pre">{text}</span>
  return <span title={text.length > 80 ? text : undefined}>{text.length > 80 ? `${text.slice(0, 80)}…` : text}</span>
}

/** Result grid for raw SQL results. `highlight` marks rows that are new/changed vs. another state. */
export function ResultGrid({ result, highlight, maxHeight = 360 }:
  { result: ResultSet; highlight?: Set<string>; maxHeight?: number }) {
  if (!result.columns.length) return null
  return (
    <div>
      <div className="overflow-auto rounded-md border border-rule" style={{ maxHeight }}>
        <table className="w-full border-collapse text-left text-sm">
          <thead className="sticky top-0 bg-paper">
            <tr>
              {result.columns.map((c, i) => (
                <th key={i} className="border-b border-rule px-3 py-2 font-semibold whitespace-nowrap">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {result.rows.map((row, r) => (
              <tr key={r} className={cx('border-b border-rule/70 last:border-0',
                highlight?.has(JSON.stringify(row)) && 'bg-bubble-soft')}>
                {row.map((v, c) => <td key={c} className="px-3 py-1.5 align-top whitespace-nowrap"><CellValue value={v} /></td>)}
              </tr>
            ))}
            {result.rows.length === 0 && (
              <tr><td colSpan={result.columns.length} className="px-3 py-4 text-center text-muted">Empty set (0 rows)</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="mt-1 text-xs text-muted">
        {result.row_count.toLocaleString()} row{result.row_count === 1 ? '' : 's'}
        {result.truncated && ` · showing the first ${result.rows.length}`}
      </p>
    </div>
  )
}

/** Rows of `after` that do not appear in `before` (used for before/after highlighting). */
export function diffRows(before?: ResultSet, after?: ResultSet): Set<string> {
  if (!before || !after) return new Set()
  const seen = new Set(before.rows.map((r) => JSON.stringify(r)))
  return new Set(after.rows.map((r) => JSON.stringify(r)).filter((r) => !seen.has(r)))
}

// --------------------------------------------------------------------------- record tables
export interface Column<T> {
  key: string
  label: string
  render?: (row: T) => ReactNode
  align?: 'left' | 'right'
  className?: string
}

export function RecordTable<T extends object>({ rows, columns, empty = 'No rows', rowKey, onRowClick }:
  { rows: T[]; columns: Column<T>[]; empty?: string; rowKey?: (row: T) => string | number; onRowClick?: (row: T) => void }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-rule bg-paper">
            {columns.map((c) => (
              <th key={c.key} className={cx('px-4 py-2 font-semibold whitespace-nowrap', c.align === 'right' && 'text-right')}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={rowKey ? rowKey(row) : i}
              className={cx('border-b border-rule/70 last:border-0', onRowClick && 'cursor-pointer hover:bg-paper')}
              onClick={onRowClick ? () => onRowClick(row) : undefined}>
              {columns.map((c) => (
                <td key={c.key} className={cx('px-4 py-2 align-top', c.align === 'right' && 'text-right tabular-nums', c.className)}>
                  {c.render ? c.render(row) : <CellValue value={(row as Record<string, unknown>)[c.key] as Cell} />}
                </td>
              ))}
            </tr>
          ))}
          {rows.length === 0 && (
            <tr><td colSpan={columns.length} className="px-4 py-8 text-center text-muted">{empty}</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
