import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { post, session, setUnauthorizedHandler, type Role, type SessionUser } from './api'

interface TokenResponse {
  access_token: string
  user: SessionUser
}

interface AuthState {
  user: SessionUser | null
  login: (username: string, password: string, accountType: 'STUDENT' | 'STAFF') => Promise<SessionUser>
  register: (body: { student_name: string; email: string; username: string; password: string }) => Promise<SessionUser>
  logout: () => void
  hasRole: (...roles: Role[]) => boolean
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(() => session.user())

  const logout = useCallback(() => {
    session.clear()
    setUser(null)
  }, [])

  useEffect(() => setUnauthorizedHandler(logout), [logout])

  const value = useMemo<AuthState>(() => ({
    user,
    async login(username, password, accountType) {
      const res = await post<TokenResponse>('/auth/login', { username, password, account_type: accountType })
      session.save(res.access_token, res.user)
      setUser(res.user)
      return res.user
    },
    async register(body) {
      const res = await post<TokenResponse>('/auth/register', body)
      session.save(res.access_token, res.user)
      setUser(res.user)
      return res.user
    },
    logout,
    hasRole: (...roles) => !!user && roles.includes(user.role),
  }), [user, logout])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
