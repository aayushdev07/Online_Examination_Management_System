import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import type { Role } from './lib/api'
import { useAuth } from './lib/auth'
import AdminDashboard from './pages/AdminDashboard'
import AttemptPage from './pages/AttemptPage'
import ExamDetail from './pages/ExamDetail'
import Exams from './pages/Exams'
import FacultyDashboard from './pages/FacultyDashboard'
import History from './pages/History'
import IndexPlans from './pages/IndexPlans'
import Login from './pages/Login'
import ObjectsExplorer from './pages/ObjectsExplorer'
import Performance from './pages/Performance'
import Procedures from './pages/Procedures'
import QuestionBank from './pages/QuestionBank'
import Results from './pages/Results'
import SchemaExplorer from './pages/SchemaExplorer'
import SqlCenter from './pages/SqlCenter'
import StudentDashboard from './pages/StudentDashboard'
import TableViewer from './pages/TableViewer'
import UsersPage from './pages/Users'

function RequireRole({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { user } = useAuth()
  if (!user) return <Navigate to="/login" replace />
  if (!roles.includes(user.role)) return <Navigate to="/" replace />
  return <>{children}</>
}

function Home() {
  const { user } = useAuth()
  if (user?.role === 'STUDENT') return <StudentDashboard />
  if (user?.role === 'ADMIN') return <AdminDashboard />
  return <FacultyDashboard />
}

const STAFF: Role[] = ['FACULTY', 'ADMIN']

export default function App() {
  const { user } = useAuth()
  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <Login />} />
      <Route element={user ? <Layout /> : <Navigate to="/login" replace />}>
        <Route index element={<Home />} />
        <Route path="attempts/:attemptId" element={<AttemptPage />} />
        <Route path="results" element={<Results />} />
        <Route path="exams" element={<RequireRole roles={STAFF}><Exams /></RequireRole>} />
        <Route path="exams/:examId" element={<RequireRole roles={STAFF}><ExamDetail /></RequireRole>} />
        <Route path="questions" element={<RequireRole roles={STAFF}><QuestionBank /></RequireRole>} />
        <Route path="admin/users" element={<RequireRole roles={['ADMIN']}><UsersPage /></RequireRole>} />
        <Route path="lab" element={<RequireRole roles={STAFF}><SqlCenter /></RequireRole>} />
        <Route path="lab/schema" element={<RequireRole roles={STAFF}><SchemaExplorer /></RequireRole>} />
        <Route path="lab/tables" element={<RequireRole roles={STAFF}><TableViewer /></RequireRole>} />
        <Route path="lab/objects" element={<RequireRole roles={STAFF}><ObjectsExplorer /></RequireRole>} />
        <Route path="lab/procedures" element={<RequireRole roles={STAFF}><Procedures /></RequireRole>} />
        <Route path="lab/plans" element={<RequireRole roles={STAFF}><IndexPlans /></RequireRole>} />
        <Route path="lab/history" element={<RequireRole roles={STAFF}><History /></RequireRole>} />
        <Route path="lab/performance" element={<RequireRole roles={STAFF}><Performance /></RequireRole>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
