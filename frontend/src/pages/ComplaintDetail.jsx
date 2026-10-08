import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, download } from '../api'
import { useAuth, isBranch, isAdmin } from '../auth'
import { Badge, Priority, Timer, STATUS, SOURCES, fmt, useLoad, useInterval, Msg } from '../util'

const REASONS = { escalated_too_early: 'Escalated too early', more_information_needed: 'More information needed', wrong_category_or_branch: 'Wrong category or branch',
  action_needed_at_lower_level: 'Action needed at lower level', decision_taken_needs_execution: 'Decision taken, needs execution', priority_reduced: 'Priority reduced', other: 'Other' }

// action -> label, tone, simple (no form), and form fields. The buttons shown come from the server (ticket.actions).
const ACTIONS = {
  pick: { label: 'Pick up', tone: 'primary', simple: true }, release: { label: 'Release to queue', simple: true },
  escalate: { label: 'Escalate', tone: 'warn', fields: [['reason', 'Why are you escalating?', 'text']] },
  deescalate: { label: 'Send back', tone: 'warn' },
  assign_branch: { label: 'Assign to branch', tone: 'primary' },
  extend_deadline: { label: 'Extend branch deadline', fields: [['minutes', 'Extra minutes (30–1440)', 'number'], ['reason', 'Reason', 'text']] },
  branch_ack: { label: 'Acknowledge', tone: 'primary', simple: true },
  branch_action_taken: { label: 'Mark action taken', tone: 'primary', fields: [['notes', 'What did you do? (min 10 characters)', 'textarea']] },
  branch_return: { label: 'Return to Head Office', fields: [['reason', 'Why can the branch not handle this?', 'text']] },
  branch_distribute: { label: 'Give to a staff member' },
  verify: { label: 'Verify branch action', tone: 'primary' },
  resolve: { label: 'Resolve', tone: 'primary', fields: [['action_taken', 'Action taken', 'text'], ['outcome', 'Outcome', 'text'], ['root_cause', 'Root cause (optional)', 'text']] },
  close: { label: 'Close', simple: true, confirm: 'Close this complaint?' }, reopen: { label: 'Reopen', fields: [['reason', 'Why reopen?', 'text']] },
  await_customer: { label: 'Waiting for customer', fields: [['reason', 'What are you waiting for?', 'text']] },
  return_for_info: { label: 'Ask branch for info', fields: [['question', 'Your question for the branch', 'textarea']] },
  resume: { label: 'Resume', simple: true }, forward: { label: 'Forward to Head Office', tone: 'primary', simple: true },
  withdraw: { label: 'Withdraw', simple: true, confirm: 'Withdraw this complaint back to draft?' },
  set_priority: { label: 'Change priority' }, merge: { label: 'Merge into another' },
  update_details: { label: 'Edit details' }, admin_force: { label: 'Admin: force move' },
}
const HIDE_IN_BAR = ['update_details']

export default function ComplaintDetail() {
  const { id } = useParams(); const { user } = useAuth(); const branch = isBranch(user)
  const { data: t, error, reload } = useLoad(() => api('/tickets/' + id), [id])
  useInterval(reload, 15000)
  const [modal, setModal] = useState(null), [flash, setFlash] = useState(''), [err, setErr] = useState('')
  const [tab, setTab] = useState('thread'), [msg, setMsg] = useState('')
  if (error) return <Msg error={error} />
  if (!t) return <div className="muted">Loading…</div>

  const run = async (action, params = {}) => {
    setErr(''); setFlash('')
    try { await api(`/tickets/${t.id}/actions`, { method: 'POST', body: { action, version: t.version, params } }); setModal(null); setFlash(ACTIONS[action].label + ' — done'); reload() }
    catch (e) { setErr(e.message); if (e.status === 409) reload() }
  }
  const click = a => { const d = ACTIONS[a]; if (d.simple) { if (d.confirm && !window.confirm(d.confirm)) return; run(a) } else setModal(a) }
  const post = async channel => {
    if (!msg.trim()) return; setErr('')
    try { await api(`/tickets/${t.id}/messages`, { method: 'POST', body: { channel, body: msg } }); setMsg(''); reload() } catch (e) { setErr(e.message) }
  }
  const upload = async e => {
    const f = e.target.files[0]; if (!f) return; const fd = new FormData(); fd.append('file', f)
    try { await api(`/tickets/${t.id}/attachments`, { method: 'POST', body: fd }); reload() } catch (x) { setErr(x.message) } e.target.value = ''
  }
  const msgs = (t.messages || []).filter(m => tab === 'customer' ? ['customer_in', 'customer_out'].includes(m.channel) : m.channel === tab)
  const channelFor = tab === 'customer' ? 'customer_out' : tab
  const canPost = tab === 'thread' ? (branch ? t.status !== 'CLOSED' && t.status !== 'DRAFT' : true) : !branch

  return (
    <div>
      <div className="row between wrap">
        <div><h1>{t.number} <Badge status={t.status} /></h1>
          <div className="row wrap muted"><span>{SOURCES[t.source]}</span><span>· Level {t.level ?? '—'}</span><Priority p={t.priority} />{t.urgent && <span className="pri critical">urgent</span>}
            {t.incomplete && <span className="pri high">incomplete details</span>}{t.cooling && <span className="pri medium">just sent back</span>}{t.repeated_movement && <span className="pri critical">repeated movement</span>}</div></div>
        <div className="timerbox"><div className="muted">Time limit</div><b><Timer t={t} /></b><small className="muted">due {fmt(t.due_at)}</small></div>
      </div>
      <Msg error={err} ok={flash} />
      <div className="actionbar">
        {t.actions.filter(a => !HIDE_IN_BAR.includes(a)).map(a => <button key={a} className={'btn ' + (ACTIONS[a].tone || '')} onClick={() => click(a)}>{ACTIONS[a].label}</button>)}
        {t.actions.length === 0 && <span className="muted">No actions available to you right now.</span>}
      </div>
      <div className="split">
        <div>
          <section className="card"><h3>Complaint</h3>
            <p className="pre">{t.description}</p>
            <dl className="kv">
              <dt>Customer</dt><dd>{t.customer?.name || '—'} · {t.customer?.mobile || t.customer?.email || '—'}</dd>
              <dt>Category</dt><dd>{t.category || '—'}</dd>
              <dt>Consignment</dt><dd>{t.consignment_no || '—'}</dd>
              <dt>Receiver</dt><dd>{t.receiver_name || '—'} {t.receiver_mobile || ''}</dd>
              <dt>Address</dt><dd>{t.address || '—'} {t.pincode || ''}</dd>
              <dt>Owner</dt><dd>{t.owner || 'Unassigned'}</dd>
              <dt>Branch</dt><dd>{t.branch || '—'}{t.origin_branch ? ` (registered by ${t.origin_branch})` : ''}</dd>
              {t.caller_number && <><dt>Call</dt><dd>{t.caller_number} {t.call_reference ? '· ' + t.call_reference : ''}</dd></>}
              <dt>Moves</dt><dd>{t.escalation_count} escalations · {t.deescalation_count} sent back</dd>
              {t.resolution && <><dt>Resolution</dt><dd>{t.resolution.action} → {t.resolution.outcome}{t.resolution.first_call ? ' (first call)' : ''}</dd></>}
            </dl>
            {t.actions.includes('update_details') && <button className="btn" onClick={() => setModal('update_details')}>Edit details</button>}
          </section>
          <section className="card"><h3>Timeline</h3>
            <ol className="timeline">{t.events.filter(e => e.type !== 'message').map(e => (
              <li key={e.id}><div><b>{e.type.replace(/_/g, ' ')}</b>{e.from_status && e.to_status && e.from_status !== e.to_status && <> · {STATUS[e.from_status]} → {STATUS[e.to_status]}</>}
                {e.trigger && e.trigger !== 'manual' && <span className="pri medium">{e.trigger.replace('_', ' ')}</span>}</div>
                {(e.reason || e.note) && <div className="muted">{e.reason_code ? REASONS[e.reason_code] + ': ' : ''}{e.reason || e.note}</div>}
                <small className="muted">{e.actor} · {fmt(e.at)}</small></li>))}</ol>
          </section>
        </div>
        <div>
          <section className="card">
            <div className="tabs">
              <button className={'tab ' + (tab === 'thread' ? 'on' : '')} onClick={() => setTab('thread')}>{branch ? 'Head Office chat' : 'Branch chat'}</button>
              {!branch && <button className={'tab ' + (tab === 'note' ? 'on' : '')} onClick={() => setTab('note')}>Internal notes</button>}
              {!branch && <button className={'tab ' + (tab === 'customer' ? 'on' : '')} onClick={() => setTab('customer')}>Customer</button>}
            </div>
            <div className="chat">{msgs.map(m => <div key={m.id} className={'bubble ' + (m.author_type === 'customer' ? 'cust' : (m.author_role?.startsWith('BRANCH') === branch && m.author_type !== 'customer' ? 'mine' : ''))}>
              <b>{m.author}</b><div className="pre">{m.body}</div><small className="muted">{fmt(m.at)}</small></div>)}
              {msgs.length === 0 && <div className="muted">Nothing here yet.</div>}</div>
            {canPost && <div className="row"><input className="grow" value={msg} onChange={e => setMsg(e.target.value)} placeholder={tab === 'customer' ? 'Message to the customer (sent on WhatsApp/SMS)…' : tab === 'note' ? 'Internal note (Head Office only)…' : 'Message…'}
              onKeyDown={e => e.key === 'Enter' && post(channelFor)} /><button className="btn primary" onClick={() => post(channelFor)}>Send</button></div>}
          </section>
          <section className="card"><h3>Attachments</h3>
            {t.attachments.map(a => <div key={a.id}><a href="#" onClick={e => { e.preventDefault(); download('/attachments/' + a.id, a.filename) }}>{a.filename}</a> <small className="muted">{Math.round(a.size / 1024)} KB</small></div>)}
            {t.attachments.length === 0 && <div className="muted">No files.</div>}
            <input type="file" onChange={upload} />
          </section>
        </div>
      </div>
      {modal && <ActionModal action={modal} t={t} user={user} onClose={() => { setModal(null); setErr('') }} onRun={run} error={err} />}
    </div>
  )
}

function ActionModal({ action, t, user, onClose, onRun, error }) {
  const def = ACTIONS[action]; const [v, setV] = useState({})
  const set = (k, x) => setV(s => ({ ...s, [k]: x }))
  const { data: branches } = useLoad(() => action === 'assign_branch' ? api('/branches') : Promise.resolve([]), [action])
  const { data: sugg } = useLoad(() => action === 'assign_branch' && t.pincode ? api('/tickets/suggest-branch?pincode=' + t.pincode) : Promise.resolve([]), [action])
  const { data: dir } = useLoad(() => ['deescalate', 'branch_distribute'].includes(action) ? api('/users/directory' + (action === 'deescalate' ? `?level=${(t.level || 2) - 1}` : '')) : Promise.resolve([]), [action])
  const fieldsFor = {
    update_details: [['address', 'Address', 'text', t.address], ['pincode', 'Pincode', 'text', t.pincode], ['consignment_no', 'Consignment number', 'text', t.consignment_no],
      ['receiver_name', 'Receiver name', 'text', t.receiver_name], ['receiver_mobile', 'Receiver mobile', 'text', t.receiver_mobile]],
  }
  const submit = e => {
    e.preventDefault()
    let p = { ...v }
    if (action === 'assign_branch') { p = { branch_id: +v.branch_id, deadline_minutes: +(v.deadline || 360), assignee_id: null } }
    if (action === 'deescalate') { p = { reason_code: v.reason_code, note: v.note, target_user_id: v.target ? +v.target : null, withdraw_branch: v.withdraw === undefined ? null : v.withdraw === 'yes', skip: !!v.skip } }
    if (action === 'branch_distribute') p = { assignee_id: +v.assignee_id }
    if (action === 'verify') p = { approve: v.approve === 'yes', note: v.note, action_taken: v.action_taken, outcome: v.outcome }
    if (action === 'extend_deadline') p.minutes = +v.minutes
    if (action === 'merge') { api('/tickets?q=' + encodeURIComponent(v.number || '')).then(r => { const hit = r.items.find(i => i.number === (v.number || '').trim().toUpperCase()); if (!hit) return alert('Complaint number not found'); onRun('merge', { into_id: hit.id }) }); return }
    if (action === 'set_priority') p = { priority: v.priority }
    if (action === 'admin_force') p = { to_status: v.to_status, reason: v.reason }
    if (action === 'update_details') { p = {}; for (const [k, , , cur] of fieldsFor.update_details) if ((v[k] ?? cur ?? '') !== (cur ?? '')) p[k] = v[k] }
    onRun(action, p)
  }
  const hasBranch = t.branch_id && t.level === 2
  return (
    <div className="overlay" onClick={onClose}>
      <form className="card modal" onClick={e => e.stopPropagation()} onSubmit={submit}>
        <h3>{def.label} · {t.number}</h3>
        {(def.fields || []).map(([k, label, type]) => <label key={k}>{label}{type === 'textarea' ? <textarea rows="3" onChange={e => set(k, e.target.value)} /> : <input type={type} onChange={e => set(k, e.target.value)} />}</label>)}
        {action === 'update_details' && fieldsFor.update_details.map(([k, label, , cur]) => <label key={k}>{label}<input defaultValue={cur || ''} onChange={e => set(k, e.target.value)} /></label>)}
        {action === 'assign_branch' && <>
          {sugg?.length > 0 && <div className="alert info">Suggested for pincode {t.pincode}: {sugg.map(s => <button type="button" key={s.id} className="chip" onClick={() => set('branch_id', s.id)}>{s.name}</button>)}</div>}
          <label>Branch<select required value={v.branch_id || ''} onChange={e => set('branch_id', e.target.value)}><option value="">Choose…</option>{(branches || []).filter(b => b.status === 'live').map(b => <option key={b.id} value={b.id}>{b.name} ({b.code})</option>)}</select></label>
          <label>Branch deadline<select value={v.deadline || 360} onChange={e => set('deadline', e.target.value)}>{[[120, '2 hours'], [240, '4 hours'], [360, '6 hours (default)'], [720, '12 hours'], [1440, '24 hours'], [2880, '48 hours']].map(([m, l]) => <option key={m} value={m}>{l}</option>)}</select></label>
          <small className="muted">If the branch has not acted by then, the complaint goes to L3 automatically.</small></>}
        {action === 'deescalate' && <>
          <label>Reason<select required value={v.reason_code || ''} onChange={e => set('reason_code', e.target.value)}><option value="">Choose…</option>{Object.entries(REASONS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
          <label>Handover note (min 20 characters) — tell them what to do<textarea required rows="3" onChange={e => set('note', e.target.value)} /></label>
          <label>Send to (optional)<select value={v.target || ''} onChange={e => set('target', e.target.value)}><option value="">Previous owner or queue</option>{(dir || []).map(u => <option key={u.id} value={u.id}>{u.name}</option>)}</select></label>
          {hasBranch && <label>The branch assignment will…<select required value={v.withdraw || ''} onChange={e => set('withdraw', e.target.value)}><option value="">Choose…</option><option value="yes">be withdrawn (branch chat becomes read-only)</option><option value="no">stay with the branch</option></select></label>}
          {isAdmin(user) && t.level === 3 && <label className="check"><input type="checkbox" onChange={e => set('skip', e.target.checked)} /> Admin: skip L2 and send to L1</label>}
          <small className="muted">The next level gets a fresh time limit. The complaint cannot be escalated again until they log an action.</small></>}
        {action === 'branch_distribute' && <label>Staff member<select required onChange={e => set('assignee_id', e.target.value)}><option value="">Choose…</option>{(dir || []).map(u => <option key={u.id} value={u.id}>{u.name}</option>)}</select></label>}
        {action === 'verify' && <>
          <label>Decision<select required onChange={e => set('approve', e.target.value)}><option value="">Choose…</option><option value="yes">Approve and resolve</option><option value="no">Send back to branch</option></select></label>
          <label>Note<input onChange={e => set('note', e.target.value)} /></label>
          {v.approve === 'yes' && <><label>Action taken<input onChange={e => set('action_taken', e.target.value)} /></label><label>Outcome<input onChange={e => set('outcome', e.target.value)} /></label></>}</>}
        {action === 'set_priority' && <label>Priority<select required onChange={e => set('priority', e.target.value)}><option value="">Choose…</option>{['low', 'medium', 'high', 'critical'].map(p => <option key={p}>{p}</option>)}</select></label>}
        {action === 'merge' && <label>Merge into complaint number<input placeholder="CRM-0000123" onChange={e => set('number', e.target.value)} /></label>}
        {action === 'admin_force' && <><label>Move to status<select required onChange={e => set('to_status', e.target.value)}><option value="">Choose…</option>{Object.entries(STATUS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
          <label>Reason (audited)<input onChange={e => set('reason', e.target.value)} /></label></>}
        <Msg error={error} />
        <div className="row"><button className="btn primary">Confirm</button><button type="button" className="btn" onClick={onClose}>Cancel</button></div>
      </form>
    </div>
  )
}
