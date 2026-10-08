import { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { api } from '../api'
import { useAuth, isBranch } from '../auth'
import { SOURCES, Msg, useLoad } from '../util'

const blank = { source: 'phone_inbound', mobile: '', name: '', email: '', category_id: '', description: '', priority: '', urgent: false,
  consignment_no: '', receiver_name: '', receiver_mobile: '', address: '', pincode: '', caller_number: '', call_reference: '', preferred_language: '' }

export default function NewComplaint() {
  const { user } = useAuth(); const nav = useNavigate(); const branch = isBranch(user)
  const { data: cats } = useLoad(() => api('/categories'), [])
  const [f, setF] = useState(blank), [err, setErr] = useState(''), [busy, setBusy] = useState(false)
  const [lookup, setLookup] = useState(null), [dup, setDup] = useState(null)
  const [resolveNow, setResolveNow] = useState(false), [res, setRes] = useState({ action_taken: '', outcome: '' })
  const set = (k, v) => setF(x => ({ ...x, [k]: v }))

  useEffect(() => {
    const m = f.mobile.replace(/\D/g, '')
    if (m.length < 10) { setLookup(null); return }
    const id = setTimeout(() => api('/tickets/check-duplicate', { method: 'POST', body: { mobile: f.mobile, consignment_no: f.consignment_no || null } })
      .then(r => { setLookup(r); if (r.customer && !f.name) set('name', r.customer.name || '') }).catch(() => {}), 400)
    return () => clearTimeout(id)
  }, [f.mobile, f.consignment_no])

  const submit = async (mode, allow = false) => {
    setBusy(true); setErr(''); setDup(null)
    const body = { ...f, mode, allow_duplicate: allow, category_id: f.category_id ? +f.category_id : null, priority: f.priority || null }
    for (const k of Object.keys(body)) if (body[k] === '') body[k] = null
    if (!branch && resolveNow) body.resolve = res
    try { const t = await api('/tickets', { method: 'POST', body }); nav(`/complaints/${t.id}`) }
    catch (e) { if (e.status === 409 && e.data?.numbers) setDup(e.data); else setErr(e.message) }
    finally { setBusy(false) }
  }
  const inp = (k, label, props = {}) => <label>{label}<input value={f[k]} onChange={e => set(k, e.target.value)} {...props} /></label>
  return (
    <div className="narrow">
      <h1>{branch ? 'Register a complaint at your branch' : 'New complaint (phone call or other)'}</h1>
      <p className="muted">{branch ? 'Register the complaint here and forward it to Head Office. You will get a complaint number to give the customer.'
        : 'Create the complaint while the customer is on the line. Only mobile, category and description are required.'}</p>
      <form className="card form" onSubmit={e => { e.preventDefault(); submit(branch ? 'queue' : 'queue') }}>
        {!branch && <label>How did it arrive?<select value={f.source} onChange={e => set('source', e.target.value)}>
          {['phone_inbound', 'phone_callback', 'walk_in', 'other', 'email', 'whatsapp'].map(k => <option key={k} value={k}>{SOURCES[k]}</option>)}</select></label>}
        <div className="two">{inp('mobile', 'Customer mobile *', { inputMode: 'tel', placeholder: '10-digit mobile' })}{inp('name', 'Customer name')}</div>
        {lookup?.customer && <div className="alert info">Existing customer: <b>{lookup.customer.name || lookup.customer.mobile}</b>.
          {lookup.open_complaints.length > 0 ? <> Open complaints: {lookup.open_complaints.map(o => <Link key={o.id} to={`/complaints/${o.id}`} target="_blank"> {o.number}</Link>)}</> : ' No open complaints.'}</div>}
        <div className="two"><label>Category *<select value={f.category_id} onChange={e => set('category_id', e.target.value)}><option value="">Choose…</option>{(cats || []).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
          {!branch && <label>Priority<select value={f.priority} onChange={e => set('priority', e.target.value)}><option value="">Default for category</option>{['low', 'medium', 'high', 'critical'].map(p => <option key={p}>{p}</option>)}</select></label>}</div>
        <label>What is the complaint? *<textarea rows="4" value={f.description} onChange={e => set('description', e.target.value)} /></label>
        <div className="two">{inp('consignment_no', 'Consignment number')}{inp('pincode', 'Delivery pincode', { inputMode: 'numeric', maxLength: 6 })}</div>
        <div className="two">{inp('receiver_name', 'Receiver name')}{inp('receiver_mobile', 'Receiver mobile')}</div>
        <label>Delivery address<textarea rows="2" value={f.address} onChange={e => set('address', e.target.value)} /></label>
        {!branch && f.source.startsWith('phone') && <div className="two">{inp('caller_number', 'Caller number')}{inp('call_reference', 'Call reference / recording ID')}</div>}
        {branch && <label className="check"><input type="checkbox" checked={f.urgent} onChange={e => set('urgent', e.target.checked)} /> Mark as urgent (alerts Head Office team leads)</label>}
        {!branch && <label className="check"><input type="checkbox" checked={resolveNow} onChange={e => setResolveNow(e.target.checked)} /> Resolved on this call</label>}
        {!branch && resolveNow && <div className="two"><label>Action taken *<input value={res.action_taken} onChange={e => setRes({ ...res, action_taken: e.target.value })} /></label>
          <label>Outcome *<input value={res.outcome} onChange={e => setRes({ ...res, outcome: e.target.value })} /></label></div>}
        <Msg error={err} />
        {dup && <div className="alert err">An open complaint already exists for this customer and consignment: {dup.numbers.map((n, i) => <Link key={n} to={`/complaints/${dup.ticket_ids[i]}`} target="_blank"> {n}</Link>)}.
          <div className="row"><button type="button" className="btn" onClick={() => submit('queue', true)}>Create anyway</button></div></div>}
        <div className="row">
          <button className="btn primary" disabled={busy || !f.mobile || !f.description}>{branch ? 'Register & forward to Head Office' : 'Create complaint'}</button>
          {!branch && !resolveNow && <button type="button" className="btn" disabled={busy || !f.mobile || !f.description} onClick={() => submit('take')}>Create & assign to me</button>}
          {branch && <button type="button" className="btn" disabled={busy || !f.description} onClick={() => submit('draft')}>Save as draft</button>}
        </div>
      </form>
    </div>
  )
}
