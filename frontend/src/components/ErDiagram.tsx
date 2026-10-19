// ER diagram drawn from live information_schema metadata (tables, columns, FKs).

export interface ErColumn { name: string; type: string; column_key: string; nullable: boolean }
export interface ErTable { name: string; type: string; columns: ErColumn[] }
export interface ErRelation { name: string; table: string; columns: string; ref_table: string; ref_columns: string }

const W = 220
const HEADER = 28
const ROW = 18

// Hand-placed layout for the OEMS tables; any other table (e.g. lab demo tables) flows below.
const POSITIONS: Record<string, [number, number]> = {
  faculty_admin: [20, 20], exam: [300, 20], exam_question: [580, 20], question: [860, 20],
  student: [20, 380], attempt: [300, 380], answer: [580, 380], exam_audit: [860, 330],
  result: [300, 640], sql_execution_log: [20, 640],
}

export default function ErDiagram({ tables, relations, onSelect, selected }:
  { tables: ErTable[]; relations: ErRelation[]; onSelect?: (name: string) => void; selected?: string | null }) {
  const base = tables.filter((t) => t.type === 'BASE TABLE')
  const boxes = new Map<string, { x: number; y: number; h: number; t: ErTable }>()
  let extraX = 20
  let extraY = 0
  const knownBottom = Math.max(0, ...base.filter((t) => POSITIONS[t.name])
    .map((t) => POSITIONS[t.name][1] + HEADER + t.columns.length * ROW))
  for (const t of base) {
    const h = HEADER + t.columns.length * ROW + 6
    let pos = POSITIONS[t.name]
    if (!pos) {
      if (!extraY) extraY = knownBottom + 40
      pos = [extraX, extraY]
      extraX += W + 60
      if (extraX > 900) { extraX = 20; extraY += 260 }
    }
    boxes.set(t.name, { x: pos[0], y: pos[1], h, t })
  }
  const width = Math.max(1100, ...[...boxes.values()].map((b) => b.x + W + 20))
  const height = Math.max(...[...boxes.values()].map((b) => b.y + b.h + 20), 300)

  const fkColumns = new Set(relations.flatMap((r) => r.columns.split(',').map((c) => `${r.table}.${c}`)))
  const colY = (box: { y: number; t: ErTable }, column: string) => {
    const idx = Math.max(0, box.t.columns.findIndex((c) => c.name === column))
    return box.y + HEADER + idx * ROW + ROW / 2
  }

  const lines = relations.flatMap((r, i) => {
    const from = boxes.get(r.table)
    const to = boxes.get(r.ref_table)
    if (!from || !to) return []
    const y1 = colY(from, r.columns.split(',')[0])
    const y2 = colY(to, r.ref_columns.split(',')[0])
    let x1: number, x2: number
    if (from.x + W < to.x) { x1 = from.x + W; x2 = to.x }
    else if (to.x + W < from.x) { x1 = from.x; x2 = to.x + W }
    else { x1 = from.x; x2 = to.x }   // same column of boxes: route on the left side
    const sameColumn = Math.abs(from.x - to.x) < W
    const mid = sameColumn ? Math.min(x1, x2) - 14 - (i % 4) * 7 : (x1 + x2) / 2 + ((i % 5) - 2) * 9
    const d = `M ${x1} ${y1} H ${mid} V ${y2} H ${x2}`
    return [{ d, x1, y1, x2, y2, name: r.name, key: `${r.name}-${i}` }]
  })

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width={width} className="max-w-none" role="img"
      aria-label="Entity relationship diagram of the database">
      <defs>
        <marker id="er-one" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" orient="auto-start-reverse">
          <path d="M 7 0 L 7 10 M 9 0 L 9 10" stroke="#1e2b45" strokeWidth="1.2" fill="none" />
        </marker>
        <marker id="er-many" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="10" markerHeight="10" orient="auto-start-reverse">
          <path d="M 10 0 L 0 5 L 10 10 M 0 5 L 10 5" stroke="#1e2b45" strokeWidth="1.2" fill="none" />
        </marker>
      </defs>
      {lines.map((l) => (
        <path key={l.key} d={l.d} fill="none" stroke="#5b6780" strokeWidth="1.3" markerStart="url(#er-many)" markerEnd="url(#er-one)">
          <title>{l.name}</title>
        </path>
      ))}
      {[...boxes.values()].map(({ x, y, h, t }) => {
        const active = selected === t.name
        return (
          <g key={t.name} transform={`translate(${x} ${y})`} onClick={() => onSelect?.(t.name)}
            className={onSelect ? 'cursor-pointer' : undefined} tabIndex={0} role="button" aria-label={`Table ${t.name}`}
            onKeyDown={(e) => e.key === 'Enter' && onSelect?.(t.name)}>
            <rect width={W} height={h} rx="6" fill="#fff" stroke={active ? '#0e7c6b' : '#c3cbd8'} strokeWidth={active ? 2 : 1} />
            <rect width={W} height={HEADER} rx="6" fill={t.name.startsWith('demo_') ? '#9a6512' : '#1e2b45'} />
            <rect y={HEADER - 6} width={W} height={6} fill={t.name.startsWith('demo_') ? '#9a6512' : '#1e2b45'} />
            <text x="10" y="19" fill="#fff" fontSize="13" fontWeight="700" fontFamily="Public Sans, sans-serif">{t.name}</text>
            {t.columns.map((c, i) => (
              <g key={c.name} transform={`translate(0 ${HEADER + i * ROW})`}>
                {c.column_key === 'PRI' && <rect x="2" y="1" width={W - 4} height={ROW - 2} fill="#fdf4d3" />}
                <text x="10" y="13" fontSize="11" fontFamily="JetBrains Mono, monospace" fill="#1e2b45"
                  fontWeight={c.column_key === 'PRI' ? 700 : 400}>
                  {c.column_key === 'PRI' ? 'PK '
                    : fkColumns.has(`${t.name}.${c.name}`) ? 'FK ' : c.column_key === 'UNI' ? 'UQ ' : '   '}{c.name}
                </text>
                <text x={W - 8} y="13" fontSize="10" textAnchor="end" fill="#5b6780" fontFamily="JetBrains Mono, monospace">
                  {c.type.replace(' unsigned', '').slice(0, 16)}{c.nullable ? '' : '*'}
                </text>
              </g>
            ))}
          </g>
        )
      })}
    </svg>
  )
}
