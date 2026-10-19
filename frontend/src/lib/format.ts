const dateTime = new Intl.DateTimeFormat(undefined, {
  day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
})

/** Server datetimes are naive MySQL DATETIME values in the server's local time. */
export function fmtDate(value: string | null | undefined): string {
  if (!value) return '—'
  const d = new Date(value.replace(' ', 'T'))
  return Number.isNaN(d.getTime()) ? value : dateTime.format(d)
}

export function fmtNumber(value: number | string | null | undefined, digits = 2): string {
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return String(value)
  return Number.isInteger(n) ? n.toLocaleString() : n.toLocaleString(undefined, { maximumFractionDigits: digits })
}

export function fmtMs(value: number | string | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const n = Number(value)
  return n >= 100 ? `${n.toFixed(0)} ms` : `${n.toFixed(n >= 10 ? 1 : 2)} ms`
}

export function fmtBytes(value: number | null | undefined): string {
  if (!value) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let n = value
  let i = 0
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i++
  }
  return `${n.toFixed(i ? 1 : 0)} ${units[i]}`
}

export function toLocalInput(value: string | null | undefined): string {
  return value ? value.replace(' ', 'T').slice(0, 16) : ''
}

export function fmtDuration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const pad = (x: number) => String(x).padStart(2, '0')
  return h ? `${h}:${pad(m)}:${pad(sec)}` : `${pad(m)}:${pad(sec)}`
}

export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ')
}
