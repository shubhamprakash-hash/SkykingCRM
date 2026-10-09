import { useEffect, useState } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { api } from '../api'
import { Msg, ROLES } from '../util'

export default function AcceptInvite() {
  const [q] = useSearchParams(); const token = q.get('token') || ''
  const [info, setInfo] = useState(null), [err, setErr] = useState(''), [pw, setPw] = useState(''), [pw2, setPw2] = useState(''), [done, setDone] = useState(false)
  useEffect(() => { api('/auth/invite-info?token=' + encodeURIComponent(token)).then(setInfo).catch(e => setErr(e.message)) }, [token])
  const submit = async e => {
    e.preventDefault(); setErr('')
    if (pw !== pw2) return setErr('Passwords do not match')
    try { await api('/auth/accept-invite', { method: 'POST', body: { token, password: pw } }); setDone(true) } catch (x) { setErr(x.message) }
  }
  return (
    <div className="center">
      <form className="card login" onSubmit={submit}>
        <h2>Join Skyking CRM</h2>
        {done ? <><div className="alert ok">Your account is ready.</div><Link className="btn primary" to="/login">Go to sign in</Link></> : <>
          {info && <p>Welcome <b>{info.name}</b>. You are joining as <b>{ROLES[info.role]}</b>{info.branch ? <> at <b>{info.branch}</b></> : ''}.</p>}
          {info?.awaiting_approval && <div className="alert err">This invitation is waiting for Head Office approval.</div>}
          {info && <>
            <label>Choose a password<input type="password" value={pw} onChange={e => setPw(e.target.value)} /></label>
            <label>Repeat password<input type="password" value={pw2} onChange={e => setPw2(e.target.value)} /></label>
            <small className="muted">At least 10 characters with letters and digits.</small></>}
          <Msg error={err} />
          {info && <button className="btn primary" disabled={!pw}>Create my account</button>}
        </>}
      </form>
    </div>
  )
}
