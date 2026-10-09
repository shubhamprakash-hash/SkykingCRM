import { useState } from 'react'
import { NavLink, Outlet, Link } from 'react-router-dom'
import { useAuth, isAdmin, isBranch } from '../auth'
import { api, DEMO } from '../api'
import { advance, resetDemo, demoClock, demoAccounts, DEMO_PASSWORD } from '../demo/engine'
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

function DemoBar() {
  const { user, login } = useAuth()
  const go = fn => { fn(); location.reload() }
  const switchTo = async email => { await login(email, DEMO_PASSWORD); location.reload() }
  return (
    <div className="demobar">
      <b>PROTOTYPE DEMO</b><span>sample data · runs in your browser</span>
      <span className="grow" />
      <span title="Demo clock (IST)">🕒 {fmt(new Date(demoClock()).toISOString())}</span>
      <button className="btn" onClick={() => go(() => advance(60, true))}>+1 working hour</button>
      <button className="btn warn" onClick={() => go(() => advance(360, true))}>+6 working hours</button>
      <button className="btn" onClick={() => go(() => advance(1440))}>+1 day</button>
      <select value={user.email} onChange={e => switchTo(e.target.value)} title="Switch user">
        {demoAccounts().map(a => <option key={a.email} value={a.email}>{a.name} ({ROLES[a.role]})</option>)}</select>
      <button className="btn" onClick={() => window.confirm('Reset all demo data?') && go(resetDemo)}>Reset</button>
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
        {DEMO && <DemoBar />}
        <header className="top"><div className="muted">Times shown in IST</div><Bell /></header>
        <Outlet />
      </main>
    </div>
  )
}
