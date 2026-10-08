import { useState } from 'react'
import { useAuth } from '../auth'
import { Msg } from '../util'

export default function Login() {
  const { login } = useAuth()
  const [u, setU] = useState(''), [p, setP] = useState(''), [err, setErr] = useState(''), [busy, setBusy] = useState(false)
  const submit = async e => {
    e.preventDefault(); setBusy(true); setErr('')
    try { await login(u, p) } catch (x) { setErr(x.message) } finally { setBusy(false) }
  }
  return (
    <div className="center">
      <form className="card login" onSubmit={submit}>
        <h2>✈ Skyking Complaint CRM</h2>
        <label>Email or mobile<input value={u} onChange={e => setU(e.target.value)} autoFocus autoComplete="username" /></label>
        <label>Password<input type="password" value={p} onChange={e => setP(e.target.value)} autoComplete="current-password" /></label>
        <Msg error={err} />
        <button className="btn primary" disabled={busy || !u || !p}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
    </div>
  )
}
