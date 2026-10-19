import { Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { RecordTable } from '../components/data'
import {
  Badge, Button, ErrorBanner, Field, Input, Modal, PageHeader, Pagination, Panel, Select, Spinner, useToast,
} from '../components/ui'
import { del, get, post, put, qs } from '../lib/api'
import { useAuth } from '../lib/auth'
import { cx, fmtDate } from '../lib/format'
import { useAction, useLoad } from '../lib/hooks'
import type { Page } from '../lib/types'

interface StudentRow { student_id: number; student_name: string; email: string; username: string; created_at: string; attempt_count: number }
interface StaffRow { faculty_admin_id: number; faculty_name: string; email: string; username: string; role: string; created_at: string; exam_count: number }

export default function UsersPage() {
  const [tab, setTab] = useState<'students' | 'staff'>('students')
  return (
    <div className="space-y-6">
      <PageHeader title="Users" description="Student and staff accounts. Passwords are stored only as bcrypt hashes." />
      <div role="tablist" className="flex gap-1 border-b border-rule">
        {(['students', 'staff'] as const).map((t) => (
          <button key={t} role="tab" type="button" aria-selected={tab === t} onClick={() => setTab(t)}
            className={cx('-mb-px border-b-2 px-4 py-2 text-sm font-semibold capitalize',
              tab === t ? 'border-ink' : 'border-transparent text-muted hover:text-ink')}>{t}</button>
        ))}
      </div>
      {tab === 'students' ? <Students /> : <Staff />}
    </div>
  )
}

function Students() {
  const toast = useToast()
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const list = useLoad(() => get<Page<StudentRow>>(`/students${qs({ search, page, page_size: 25 })}`), [search, page])
  const remove = useAction(async (s: StudentRow) => {
    await del(`/students/${s.student_id}`)
    toast('success', `Deleted ${s.student_name}`)
    list.reload()
  })
  return (
    <Panel flush title={`${(list.data?.total ?? 0).toLocaleString()} students`}
      actions={<Input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1) }} placeholder="Search name, e-mail, username" className="w-72" aria-label="Search students" />}>
      <div className="px-4 pt-3"><ErrorBanner error={list.error ?? remove.error} /></div>
      {list.loading && !list.data ? <Spinner /> : (
        <>
          <RecordTable<StudentRow> rows={list.data?.items ?? []} rowKey={(r) => r.student_id}
            columns={[
              { key: 'student_id', label: 'ID', align: 'right' },
              { key: 'student_name', label: 'Name', render: (r) => <span className="font-medium">{r.student_name}</span> },
              { key: 'username', label: 'Username' },
              { key: 'email', label: 'E-mail' },
              { key: 'attempt_count', label: 'Attempts', align: 'right' },
              { key: 'created_at', label: 'Registered', render: (r) => fmtDate(r.created_at) },
              { key: 'del', label: '', render: (r) => (
                <Button variant="ghost" aria-label={`Delete ${r.student_name}`} onClick={() => remove.run(r)}
                  title={r.attempt_count ? 'Blocked by the foreign key on attempt' : 'Delete'}><Trash2 className="size-4" /></Button>) },
            ]} />
          {list.data && <Pagination page={page} pageSize={25} total={list.data.total} onPage={setPage} />}
        </>
      )}
    </Panel>
  )
}

function Staff() {
  const toast = useToast()
  const { user } = useAuth()
  const [creating, setCreating] = useState(false)
  const list = useLoad(() => get<StaffRow[]>('/staff'))
  const setRole = useAction(async (s: StaffRow, role: string) => {
    await put(`/staff/${s.faculty_admin_id}`, { role })
    toast('success', `${s.faculty_name} is now ${role.toLowerCase()}`)
    list.reload()
  })
  const remove = useAction(async (s: StaffRow) => {
    await del(`/staff/${s.faculty_admin_id}`)
    toast('success', `Deleted ${s.faculty_name}`)
    list.reload()
  })
  return (
    <Panel flush title="Staff accounts" actions={<Button onClick={() => setCreating(true)}><Plus className="size-4" /> New staff account</Button>}>
      <div className="px-4 pt-3"><ErrorBanner error={list.error ?? setRole.error ?? remove.error} /></div>
      <RecordTable<StaffRow> rows={list.data ?? []} rowKey={(r) => r.faculty_admin_id}
        columns={[
          { key: 'faculty_admin_id', label: 'ID', align: 'right' },
          { key: 'faculty_name', label: 'Name', render: (r) => <span className="font-medium">{r.faculty_name}</span> },
          { key: 'username', label: 'Username' },
          { key: 'email', label: 'E-mail' },
          { key: 'role', label: 'Role', render: (r) => r.faculty_admin_id === user?.id ? <Badge>{r.role}</Badge> : (
            <Select value={r.role} onChange={(e) => setRole.run(r, e.target.value)} className="w-32" aria-label={`Role of ${r.faculty_name}`}>
              <option value="FACULTY">faculty</option><option value="ADMIN">admin</option>
            </Select>) },
          { key: 'exam_count', label: 'Exams', align: 'right' },
          { key: 'del', label: '', render: (r) => r.faculty_admin_id !== user?.id && (
            <Button variant="ghost" aria-label={`Delete ${r.faculty_name}`} onClick={() => remove.run(r)}><Trash2 className="size-4" /></Button>) },
        ]} />
      {creating && <StaffForm onClose={() => setCreating(false)} onSaved={() => { setCreating(false); toast('success', 'Account created'); list.reload() }} />}
    </Panel>
  )
}

function StaffForm({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({ faculty_name: '', email: '', username: '', password: '', role: 'FACULTY' })
  const save = useAction(async () => { await post('/staff', form); onSaved() })
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value })
  return (
    <Modal open title="New staff account" onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button busy={save.busy} onClick={() => save.run()}>Create account</Button></>}>
      <div className="grid gap-4">
        <Field label="Full name"><Input value={form.faculty_name} onChange={set('faculty_name')} /></Field>
        <Field label="E-mail"><Input type="email" value={form.email} onChange={set('email')} /></Field>
        <Field label="Username"><Input value={form.username} onChange={set('username')} /></Field>
        <Field label="Password" hint="At least 8 characters with a letter and a digit"><Input type="password" value={form.password} onChange={set('password')} /></Field>
        <Field label="Role"><Select value={form.role} onChange={set('role')}><option value="FACULTY">faculty</option><option value="ADMIN">admin</option></Select></Field>
        <ErrorBanner error={save.error} />
      </div>
    </Modal>
  )
}
