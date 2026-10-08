import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth, isAdmin, isBranch } from './auth'
import Layout from './components/Layout'
import Login from './pages/Login'
import AcceptInvite from './pages/AcceptInvite'
import Dashboard from './pages/Dashboard'
import Complaints from './pages/Complaints'
import NewComplaint from './pages/NewComplaint'
import ComplaintDetail from './pages/ComplaintDetail'
import Branches from './pages/Branches'
import Team from './pages/Team'
import Helpdesk from './pages/Helpdesk'
import Settings from './pages/Settings'

export default function App() {
  const { user } = useAuth()
  if (user === undefined) return <div className="center muted">Loading…</div>
  return (
    <Routes>
      <Route path="/accept-invite" element={<AcceptInvite />} />
      <Route path="/login" element={user ? <Navigate to="/" /> : <Login />} />
      {user ? (
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="complaints" element={<Complaints />} />
          <Route path="complaints/new" element={<NewComplaint />} />
          <Route path="complaints/:id" element={<ComplaintDetail />} />
          <Route path="helpdesk" element={<Helpdesk />} />
          {(isAdmin(user)) && <Route path="branches" element={<Branches />} />}
          {(isAdmin(user) || user.role === 'BRANCH_ADMIN') && <Route path="team" element={<Team />} />}
          {isAdmin(user) && <Route path="settings" element={<Settings />} />}
          <Route path="*" element={<Navigate to="/" />} />
        </Route>
      ) : <Route path="*" element={<Navigate to="/login" />} />}
    </Routes>
  )
}
