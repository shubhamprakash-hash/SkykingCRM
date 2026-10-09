import { useState } from 'react'
import { useAuth } from '../auth'
import { Msg, ROLES } from '../util'
import { DEMO } from '../api'
import { demoAccounts, DEMO_PASSWORD } from '../demo/engine'

export default function Login() {
  const { login } = useAuth()
  const [u, setU] = useState(''), [p, setP] = useState(''), [err, setErr] = useState(''), [busy, setBusy] = useState(false)
  const submit = async e => {
    e.preventDefault(); setBusy(true); setErr('')
    try { await login(u, p) } catch (x) { setErr(x.message) } finally { setBusy(false) }
  }
  return (
    <div className="center">
      <form className={"card login" + (DEMO ? " wide" : "")} onSubmit={submit}>
        <h2>✈ Skyking Complaint CRM</h2>
        <label>Email or mobile<input value={u} onChange={e => setU(e.target.value)} autoFocus autoComplete="username" /></label>
        <label>Password<input type="password" value={p} onChange={e => setP(e.target.value)} autoComplete="current-password" /></label>
        <Msg error={err} />
        <button className="btn primary" disabled={busy || !u || !p}>{busy ? 'Signing in…' : 'Sign in'}</button>
        {DEMO && <div className="demo-login">
          <div className="alert info"><b>Prototype demo.</b> Sample data, runs in your browser. Pick a role to sign in (password for all: <code>{DEMO_PASSWORD}</code>).</div>
          <div className="demo-grid">{demoAccounts().map(a => <button type="button" key={a.email} className="btn" disabled={busy}
            onClick={async () => { setBusy(true); try { await login(a.email, DEMO_PASSWORD) } catch (x) { setErr(x.message); setBusy(false) } }}>
            <b>{a.name}</b><br /><small className="muted">{ROLES[a.role]}{a.branch ? ' · ' + a.branch : ''}</small></button>)}</div>
        </div>}
      </form>
    </div>
  )
}
