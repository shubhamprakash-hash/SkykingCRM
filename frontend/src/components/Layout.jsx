import { useState } from 'react'
import { NavLink, Outlet, Link } from 'react-router-dom'
import { useAuth, isAdmin, isBranch } from '../auth'
import { api } from '../api'
import { ROLES, fmt, useInterval, useLoad } from '../util'

function Bell() {
  const [open, setOpen] = useState(false)
  const { data, reload } = useLoad(() => api('/notifications'), [])
  useInterval(reload, 30000)
  const unread = data?.unread || 0
  const toggle = async () => { setOpen(o => !o); if (!open && unread) { await api('/notifications/read', { method: 'POST' }); setTimeout(reload, 500) } }
  return (
    <div className="bell">
      <button className="btn ghost" onClick={toggle} aria-label="Notifications">🔔{unread > 0 && <b className="count">{unread}</b>}</button>
      {open && (
        <div className="drop">
          {(data?.items || []).length === 0 && <div className="muted pad">No notifications</div>}
          {(data?.items || []).map(n => (
            <Link key={n.id} to={n.ticket_id ? `/complaints/${n.ticket_id}` : '/'} onClick={() => setOpen(false)} className={'note ' + (n.read ? '' : 'new')}>
              <div>{n.text}</div><small className="muted">{fmt(n.at)}</small>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}

export default function Layout() {
  const { user, logout } = useAuth()
  const b = isBranch(user)
  return (
    <div className="shell">
      <aside className="side">
        <div className="brand">✈ Skyking<small>Complaint CRM</small></div>
        <nav>
          <NavLink to="/" end>Dashboard</NavLink>
          <NavLink to="/complaints">Complaints</NavLink>
          <NavLink to="/complaints/new">+ New complaint</NavLink>
          <NavLink to="/helpdesk">{b ? 'Head Office desk' : 'Branch help desk'}</NavLink>
          {(isAdmin(user) || user.role === 'BRANCH_ADMIN') && <NavLink to="/team">Team & invitations</NavLink>}
          {isAdmin(user) && <NavLink to="/branches">Branches</NavLink>}
          {isAdmin(user) && <NavLink to="/settings">Rules & SLA</NavLink>}
        </nav>
        <div className="me">
          <div><b>{user.name}</b></div>
          <small>{ROLES[user.role]}{user.branch ? ' · ' + user.branch : ''}</small>
          <button className="btn ghost" onClick={logout}>Sign out</button>
        </div>
      </aside>
      <main className="main">
        <header className="top"><div className="muted">Times shown in IST</div><Bell /></header>
        <Outlet />
      </main>
    </div>
  )
}
