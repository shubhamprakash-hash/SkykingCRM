import { useState } from 'react'
import { api, linkBase } from '../api'
import { useAuth, isAdmin } from '../auth'
import { ROLES, fmt, useLoad, Msg } from '../util'

export default function Team() {
  const { user } = useAuth(); const admin = isAdmin(user)
  const users = useLoad(() => api('/users'), []), invs = useLoad(() => api('/invitations'), [])
  const { data: branches } = useLoad(() => admin ? api('/branches') : Promise.resolve([]), [])
  const [f, setF] = useState({ name: '', role: admin ? 'L1' : 'BRANCH_STAFF', mobile: '', email: '', branch_id: '' }), [err, setErr] = useState(''), [link, setLink] = useState('')
  const set = (k, v) => setF(x => ({ ...x, [k]: v }))
  const roles = admin ? ['L1', 'L2', 'L3', 'REGIONAL_MANAGER', 'HO_ADMIN', 'BRANCH_ADMIN', 'BRANCH_STAFF'] : ['BRANCH_STAFF', 'BRANCH_ADMIN']
  const needsBranch = f.role.startsWith('BRANCH')
  const invite = async e => {
    e.preventDefault(); setErr(''); setLink('')
    try { const r = await api('/invitations', { method: 'POST', body: { ...f, branch_id: f.branch_id ? +f.branch_id : null, mobile: f.mobile || null, email: f.email || null } })
      setLink(linkBase() + r.invite_link + (r.status === 'awaiting_approval' ? '   (works after Head Office approves)' : '')); setF({ ...f, name: '', mobile: '', email: '' }); invs.reload() } catch (x) { setErr(x.message) }
  }
  const call = async (path, method = 'POST', body) => { setErr(''); try { const r = await api(path, { method, body }); if (r.reset_link) setLink(linkBase() + r.reset_link); users.reload(); invs.reload() } catch (x) { setErr(x.message) } }
  return (
    <div>
      <h1>Team & invitations</h1>
      <Msg error={err || users.error} />
      {link && <div className="alert info">Invitation link — send it to the person (WhatsApp / SMS / email):<br /><code className="copy">{link}</code></div>}
      <div className="grid2">
        <form className="card form" onSubmit={invite}><h3>Invite a new user</h3>
          <label>Full name *<input value={f.name} onChange={e => set('name', e.target.value)} /></label>
          <div className="two"><label>Mobile<input value={f.mobile} onChange={e => set('mobile', e.target.value)} /></label><label>Email<input value={f.email} onChange={e => set('email', e.target.value)} /></label></div>
          <label>Role<select value={f.role} onChange={e => set('role', e.target.value)}>{roles.map(r => <option key={r} value={r}>{ROLES[r]}</option>)}</select></label>
          {admin && needsBranch && <label>Branch<select required value={f.branch_id} onChange={e => set('branch_id', e.target.value)}><option value="">Choose…</option>{(branches || []).map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</select></label>}
          {!admin && <small className="muted">New users join your branch only. New Branch Admins need Head Office approval.</small>}
          <button className="btn primary" disabled={!f.name || (!f.mobile && !f.email)}>Create invitation</button></form>
        <section className="card"><h3>Invitations</h3>
          <table><thead><tr><th>Name</th><th>Role</th><th>Status</th><th></th></tr></thead><tbody>
            {(invs.data || []).map(i => <tr key={i.id}><td>{i.name}<br /><small className="muted">{i.branch}</small></td><td>{ROLES[i.role]}</td><td>{i.status.replace('_', ' ')}</td>
              <td className="row">{i.status === 'awaiting_approval' && admin && <button className="btn" onClick={() => call(`/invitations/${i.id}/approve`)}>Approve</button>}
                {['pending', 'awaiting_approval'].includes(i.status) && <button className="btn" onClick={() => call(`/invitations/${i.id}/revoke`)}>Revoke</button>}</td></tr>)}</tbody></table></section>
      </div>
      <h3>People</h3>
      <div className="tablewrap"><table><thead><tr><th>Name</th><th>Role</th><th>Branch</th><th>Contact</th><th>Last login</th><th>Status</th><th></th></tr></thead>
        <tbody>{(users.data || []).map(u => <tr key={u.id}><td><b>{u.name}</b>{u.is_team_lead && <span className="pri medium">team lead</span>}</td><td>{ROLES[u.role]}</td><td>{u.branch || '—'}</td><td>{u.email || u.mobile}</td><td>{fmt(u.last_login)}</td>
          <td><span className={'badge ' + (u.status === 'active' ? 'ok' : 'hot')}>{u.status}</span></td>
          <td className="row">{u.id !== user.id && (u.status === 'active'
            ? <button className="btn" onClick={() => window.confirm('Deactivate this user? Their open complaints go back to the queue.') && call(`/users/${u.id}`, 'PATCH', { status: 'suspended' })}>Deactivate</button>
            : <button className="btn" onClick={() => call(`/users/${u.id}`, 'PATCH', { status: 'active' })}>Reactivate</button>)}
            <button className="btn" onClick={() => call(`/users/${u.id}/reset-password`)}>Reset password</button>
            {admin && ['L1', 'L2', 'L3'].includes(u.role) && <button className="btn" onClick={() => call(`/users/${u.id}`, 'PATCH', { is_team_lead: !u.is_team_lead })}>{u.is_team_lead ? 'Remove lead' : 'Make lead'}</button>}</td></tr>)}</tbody></table></div>
    </div>
  )
}
