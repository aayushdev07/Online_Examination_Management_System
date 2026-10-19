import {
  BookOpen, ClipboardList, Database, FileBarChart, GaugeCircle, History, Layers, LayoutDashboard,
  ListTree, LogOut, Menu, Network, Table2, TerminalSquare, Users, Workflow, X,
} from 'lucide-react'
import { useState, type ComponentType } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import type { Role } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cx } from '../lib/format'

interface NavItem { to: string; label: string; icon: ComponentType<{ className?: string }>; roles: Role[]; end?: boolean }
interface NavGroup { title?: string; items: NavItem[] }

const STAFF: Role[] = ['FACULTY', 'ADMIN']
const ALL: Role[] = ['STUDENT', 'FACULTY', 'ADMIN']

const NAV: NavGroup[] = [
  {
    items: [
      { to: '/', label: 'Dashboard', icon: LayoutDashboard, roles: ALL, end: true },
      { to: '/exams', label: 'Examinations', icon: ClipboardList, roles: STAFF },
      { to: '/questions', label: 'Question bank', icon: BookOpen, roles: STAFF },
      { to: '/results', label: 'Results & reports', icon: FileBarChart, roles: ALL },
      { to: '/admin/users', label: 'Users', icon: Users, roles: ['ADMIN'] },
    ],
  },
  {
    title: 'DBMS lab',
    items: [
      { to: '/lab', label: 'SQL Command Center', icon: TerminalSquare, roles: STAFF, end: true },
      { to: '/lab/schema', label: 'Schema explorer', icon: Network, roles: STAFF },
      { to: '/lab/tables', label: 'Table data', icon: Table2, roles: STAFF },
      { to: '/lab/objects', label: 'Views & triggers', icon: Layers, roles: STAFF },
      { to: '/lab/procedures', label: 'Procedures', icon: Workflow, roles: STAFF },
      { to: '/lab/plans', label: 'Indexes & plans', icon: ListTree, roles: STAFF },
      { to: '/lab/history', label: 'Execution history', icon: History, roles: STAFF },
      { to: '/lab/performance', label: 'Performance', icon: GaugeCircle, roles: STAFF },
    ],
  },
]

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <svg viewBox="0 0 32 32" className="size-8" aria-hidden>
        <rect width="32" height="32" rx="6" fill="#ffffff" fillOpacity="0.08" />
        <circle cx="11" cy="11" r="3.4" fill="#F7D774" />
        <circle cx="21" cy="11" r="3.4" fill="none" stroke="#fff" strokeOpacity=".7" strokeWidth="1.5" />
        <circle cx="11" cy="21" r="3.4" fill="none" stroke="#fff" strokeOpacity=".7" strokeWidth="1.5" />
        <circle cx="21" cy="21" r="3.4" fill="#F7D774" />
      </svg>
      <div className="leading-tight">
        <div className="font-bold tracking-tight text-white">OEMS</div>
        <div className="text-xs text-white/60">Examinations + DBMS lab</div>
      </div>
    </div>
  )
}

export default function Layout() {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)
  if (!user) return null

  const sidebar = (
    <nav className="flex h-full flex-col gap-6 overflow-y-auto px-3 py-5" aria-label="Main">
      <div className="px-2"><Logo /></div>
      {NAV.map((group, gi) => {
        const items = group.items.filter((i) => i.roles.includes(user.role))
        if (!items.length) return null
        return (
          <div key={gi}>
            {group.title && (
              <div className="mb-1 flex items-center gap-2 px-2 text-xs font-semibold text-white/50">
                <Database className="size-3.5" aria-hidden /> {group.title}
              </div>
            )}
            <ul className="space-y-0.5">
              {items.map((item) => (
                <li key={item.to}>
                  <NavLink to={item.to} end={item.end} onClick={() => setOpen(false)}
                    className={({ isActive }) => cx('flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm',
                      isActive ? 'bg-white/12 font-semibold text-white' : 'text-white/75 hover:bg-white/6 hover:text-white')}>
                    <item.icon className="size-4 shrink-0" />
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        )
      })}
      <div className="mt-auto rounded-md bg-white/6 p-3 text-sm text-white">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate font-semibold">{user.name}</span>
          <span className="rounded bg-white/15 px-2 py-0.5 text-xs font-semibold text-white">{user.role.toLowerCase()}</span>
        </div>
        <div className="truncate text-xs text-white/60">{user.username}</div>
        <button type="button" onClick={logout}
          className="mt-3 inline-flex items-center gap-1.5 text-xs font-semibold text-white/80 hover:text-white">
          <LogOut className="size-3.5" /> Sign out
        </button>
      </div>
    </nav>
  )

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[248px_1fr]">
      <aside className="sticky top-0 hidden h-screen bg-ink lg:block">{sidebar}</aside>
      <div className="flex items-center justify-between bg-ink px-4 py-3 lg:hidden">
        <Logo />
        <button type="button" onClick={() => setOpen(!open)} aria-label="Toggle navigation" className="text-white">
          {open ? <X /> : <Menu />}
        </button>
      </div>
      {open && <div className="bg-ink lg:hidden">{sidebar}</div>}
      <main className="min-w-0 px-4 py-6 sm:px-8 lg:py-8">
        <Outlet />
      </main>
    </div>
  )
}

