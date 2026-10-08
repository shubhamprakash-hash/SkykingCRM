import { useState } from 'react'
import { api } from '../api'
import { useLoad, Msg } from '../util'

const RULES = [
  ['default_minutes', 'Default unattended limit (minutes)'], ['critical_minutes', 'Critical priority limit (minutes)'],
  ['branch_deadline_default', 'Branch deadline default (minutes)'], ['branch_deadline_min', 'Branch deadline minimum'], ['branch_deadline_max', 'Branch deadline maximum'],
  ['max_extensions', 'Deadline extensions allowed'], ['max_deescalations', 'Send-backs allowed per complaint'], ['repeated_movement_at', 'Flag "repeated movement" after N level changes'],
  ['info_limit_minutes', 'Branch must answer info requests within (minutes)'], ['l3_repeat_minutes', 'Repeat L3 breach alert every (minutes)'],
  ['auto_close_hours', 'Auto-close resolved complaints after (hours)'], ['reopen_window_days', 'Reopen window (days)'], ['min_handover_chars', 'Minimum handover note length'],
]

export default function Settings() {
  const { data, error, reload } = useLoad(() => api('/settings'), [])
  const [rules, setRules] = useState({}), [cal, setCal] = useState({}), [msg, setMsg] = useState(''), [err, setErr] = useState('')
  if (!data) return <Msg error={error} />
  const R = { ...data.rules, ...rules }, C = { ...data.calendar, ...cal }
  const save = async (path, body) => { setErr(''); setMsg(''); try { await api(path, { method: 'PUT', body }); setMsg('Saved'); setRules({}); setCal({}); reload() } catch (x) { setErr(x.message) } }
  const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
  return (
    <div>
      <h1>Rules & SLA</h1><Msg error={err} ok={msg} />
      <div className="grid2">
        <section className="card form"><h3>Escalation rules</h3>
          {RULES.map(([k, l]) => <label key={k}>{l}<input type="number" value={R[k]} onChange={e => setRules({ ...rules, [k]: +e.target.value })} /></label>)}
          <label>When a branch misses its deadline<select value={R.branch_breach_action} onChange={e => setRules({ ...rules, branch_breach_action: e.target.value })}><option value="escalate_l3">Escalate to L3 automatically</option><option value="alert_l2">Only alert L2</option></select></label>
          <label>HO approval of branch-invited users<select value={R.staff_approval} onChange={e => setRules({ ...rules, staff_approval: e.target.value })}><option value="none">Not required</option><option value="branch_admin">New Branch Admins only</option><option value="all">Everyone</option></select></label>
          <button className="btn primary" onClick={() => save('/settings/rules', rules)} disabled={!Object.keys(rules).length}>Save rules</button></section>
        <section className="card form"><h3>Clock (when do timers run?)</h3>
          <label>Mode<select value={C.mode} onChange={e => setCal({ ...cal, mode: e.target.value })}><option value="business">Working hours only</option><option value="24x7">24 × 7</option></select></label>
          <div className="two"><label>Opens (IST)<input type="time" value={C.start} onChange={e => setCal({ ...cal, start: e.target.value })} /></label><label>Closes (IST)<input type="time" value={C.end} onChange={e => setCal({ ...cal, end: e.target.value })} /></label></div>
          <div className="row wrap">{days.map((d, i) => <label key={d} className="check"><input type="checkbox" checked={C.days.includes(i)} onChange={e => setCal({ ...cal, days: e.target.checked ? [...C.days, i].sort() : C.days.filter(x => x !== i) })} />{d}</label>)}</div>
          <label>Holidays (YYYY-MM-DD, comma separated)<input value={(C.holidays || []).join(', ')} onChange={e => setCal({ ...cal, holidays: e.target.value.split(/[,\s]+/).filter(Boolean) })} /></label>
          <button className="btn primary" onClick={() => save('/settings/calendar', cal)} disabled={!Object.keys(cal).length}>Save clock</button>
          <h3>Time limit per level and priority (minutes)</h3>
          <table><thead><tr><th>Level</th>{['low', 'medium', 'high', 'critical'].map(p => <th key={p}>{p}</th>)}</tr></thead><tbody>
            {[1, 2, 3].map(l => <tr key={l}><td>L{l}</td>{['low', 'medium', 'high', 'critical'].map(p => { const row = data.policies.find(x => x.level === l && x.priority === p)
              return <td key={p}><input style={{ width: 70 }} type="number" defaultValue={row.minutes} onBlur={e => +e.target.value !== row.minutes && save('/settings/policy', { level: l, priority: p, minutes: +e.target.value })} /></td> })}</tr>)}</tbody></table>
        </section>
      </div>
    </div>
  )
}
