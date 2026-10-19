// Thin fetch wrapper around the FastAPI backend. All data shown in the UI
// comes from these calls — nothing is mocked or computed client-side.

export type Role = 'STUDENT' | 'FACULTY' | 'ADMIN'

export interface SessionUser {
  id: number
  role: Role
  name: string
  username: string
  email: string
}

export class ApiError extends Error {
  status: number
  code: string
  details: unknown
  requestId?: string

  constructor(status: number, code: string, message: string, details?: unknown, requestId?: string) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
    this.requestId = requestId
  }
}

const TOKEN_KEY = 'oems.token'
const USER_KEY = 'oems.user'

export const session = {
  token: (): string | null => sessionStorage.getItem(TOKEN_KEY),
  user: (): SessionUser | null => {
    const raw = sessionStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as SessionUser) : null
  },
  save(token: string, user: SessionUser) {
    sessionStorage.setItem(TOKEN_KEY, token)
    sessionStorage.setItem(USER_KEY, JSON.stringify(user))
  },
  clear() {
    sessionStorage.removeItem(TOKEN_KEY)
    sessionStorage.removeItem(USER_KEY)
  },
}

let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

export async function api<T = unknown>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = session.token()
  if (token) headers.Authorization = `Bearer ${token}`
  if (init.body !== undefined) headers['Content-Type'] = 'application/json'

  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      method: init.method ?? 'GET',
      headers,
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    })
  } catch {
    throw new ApiError(0, 'network_error', 'The API server is not reachable. Is the backend running on port 8000?')
  }

  if (response.status === 204) return undefined as T
  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = null
    }
  }
  if (!response.ok) {
    const err = (payload as { error?: { code: string; message: string; details?: unknown; request_id?: string } })?.error
    if (response.status === 401 && path !== '/auth/login') onUnauthorized?.()
    throw new ApiError(
      response.status,
      err?.code ?? 'http_error',
      err?.message ?? `Request failed with status ${response.status}`,
      err?.details,
      err?.request_id ?? response.headers.get('X-Request-ID') ?? undefined,
    )
  }
  return payload as T
}

export const get = <T,>(path: string) => api<T>(path)
export const post = <T,>(path: string, body?: unknown) => api<T>(path, { method: 'POST', body: body ?? {} })
export const put = <T,>(path: string, body: unknown) => api<T>(path, { method: 'PUT', body })
export const del = (path: string) => api<void>(path, { method: 'DELETE' })

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== '') search.set(k, String(v))
  }
  const s = search.toString()
  return s ? `?${s}` : ''
}
