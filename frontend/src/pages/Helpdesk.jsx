import { useState } from 'react'
import { api } from '../api'
import { useAuth, isBranch } from '../auth'
import { fmt, useLoad, useInterval, Msg } from '../util'

export default function Helpdesk() {
  const { user } = useAuth(); const b = isBranch(user)
  const { data: branches } = useLoad(() => b ? Promise.resolve([]) : api('/branches'), [])
  const [bid, setBid] = useState('')
  const q = b ? '/helpdesk' : (bid ? `/helpdesk?branch_id=${bid}` : null)
  const { data, error, reload } = useLoad(() => q ? api(q) : Promise.resolve([]), [q])
  useInterval(reload, 10000)
  const [body, setBody] = useState(''), [err, setErr] = useState('')
  const send = async e => {
    e.preventDefault(); setErr('')
    try { await api('/helpdesk', { method: 'POST', body: { body, branch_id: b ? null : +bid } }); setBody(''); reload() } catch (x) { setErr(x.message) }
  }
  return (
    <div className="narrow">
      <h1>{b ? 'Head Office help desk' : 'Branch help desk'}</h1>
      <p className="muted">{b ? 'Ask Head Office anything that is not about one specific complaint. For a complaint, use the message box inside that complaint.' : 'Messages from branches that are not tied to a complaint.'}</p>
      {!b && <select value={bid} onChange={e => setBid(e.target.value)}><option value="">Choose a branch…</option>{(branches || []).map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select>}
      <Msg error={error || err} />
      <div className="card chat">
        {(data || []).map(m => <div key={m.id} className={'bubble ' + (m.author_role?.startsWith('BRANCH') === b ? 'mine' : '')}><b>{m.author}</b><div>{m.body}</div><small className="muted">{fmt(m.at)}</small></div>)}
        {data && data.length === 0 && <div className="muted">No messages yet.</div>}
      </div>
      <form className="row" onSubmit={send}><input className="grow" value={body} onChange={e => setBody(e.target.value)} placeholder="Type a message…" disabled={!b && !bid} />
        <button className="btn primary" disabled={!body.trim() || (!b && !bid)}>Send</button></form>
    </div>
  )
}
