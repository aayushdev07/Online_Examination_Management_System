import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from './api'

export interface Loadable<T> {
  data: T | null
  error: ApiError | null
  loading: boolean
  reload: () => void
}

/** Runs an async loader on mount and whenever `deps` change. */
export function useLoad<T>(loader: () => Promise<T>, deps: unknown[] = []): Loadable<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)
  const loaderRef = useRef(loader)
  loaderRef.current = loader

  useEffect(() => {
    let alive = true
    setLoading(true)
    loaderRef
      .current()
      .then((value) => {
        if (!alive) return
        setData(value)
        setError(null)
      })
      .catch((e: unknown) => {
        if (!alive) return
        setError(e instanceof ApiError ? e : new ApiError(0, 'client_error', String(e)))
      })
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  const reload = useCallback(() => setTick((t) => t + 1), [])
  return { data, error, loading, reload }
}

/** Wraps a mutation: tracks busy state and the last error. */
export function useAction<A extends unknown[], R>(fn: (...args: A) => Promise<R>) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const run = useCallback(
    async (...args: A): Promise<R | undefined> => {
      setBusy(true)
      setError(null)
      try {
        return await fn(...args)
      } catch (e) {
        setError(e instanceof ApiError ? e : new ApiError(0, 'client_error', String(e)))
        return undefined
      } finally {
        setBusy(false)
      }
    },
    [fn],
  )
  return { run, busy, error, setError }
}
