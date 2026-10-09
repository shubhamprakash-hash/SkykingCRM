import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, download } from '../api'
import { useAuth, isBranch } from '../auth'
import { Badge, Priority, Timer, STATUS, SOURCES, fmt, useLoad, useInterval, Msg } from '../util'

const TABS = [['', 'All'], ['queue=true', 'Waiting in queue'], ['mine=true', 'Mine'], ['overdue=true', 'Overdue'], ['open_only=true', 'Open']]

export default function Complaints() {
  const { user } = useAuth()
  const [sp, setSp] = useSearchParams()
  const [q, setQ] = useState(sp.get('q') || '')
  const [status, setStatus] = useState(''), [level, setLevel] = useState(''), [priority, setPriority] = useState(''), [source, setSource] = useState('')
  const [page, setPage] = useState(1)
  const tab = TABS.find(t => t[0] && sp.has(t[0].split('=')[0]))?.[0] || ''
  const params = new URLSearchParams()
  if (tab) { const [k, v] = tab.split('='); params.set(k, v) }
  if (q) params.set('q', q); if (status) params.set('status', status); if (level) params.set('level', level)
  if (priority) params.set('priority', priority); if (source) params.set('source', source); params.set('page', page)
  const { data, error, reload } = useLoad(() => api('/tickets?' + params.toString()), [params.toString()])
  useInterval(reload, 30000)
  const setTab = t => { setPage(1); setSp(t ? Object.fromEntries([t.split('=')]) : {}) }
  return (
    <div>
      <div className="row between"><h1>Complaints</h1>
        <div className="row">
          {!isBranch(user) && <button className="btn" onClick={() => download('/reports/export.csv', 'complaints.csv')}>Export CSV</button>}
          <Link className="btn primary" to="/complaints/new">+ New complaint</Link></div></div>
      <div className="tabs">{TABS.map(([v, l]) => <button key={l} className={'tab ' + (v === tab ? 'on' : '')} onClick={() => setTab(v)}>{l}</button>)}</div>
      <div className="filters">
        <input placeholder="Search number, mobile, name, consignment…" value={q} onChange={e => { setQ(e.target.value); setPage(1) }} />
        <select value={status} onChange={e => setStatus(e.target.value)}><option value="">Any status</option>{Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <select value={level} onChange={e => setLevel(e.target.value)}><option value="">Any level</option><option value="1">L1</option><option value="2">L2</option><option value="3">L3</option></select>
        <select value={priority} onChange={e => setPriority(e.target.value)}><option value="">Any priority</option>{['low', 'medium', 'high', 'critical'].map(p => <option key={p}>{p}</option>)}</select>
        <select value={source} onChange={e => setSource(e.target.value)}><option value="">Any source</option>{Object.entries(SOURCES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
      </div>
      <Msg error={error} />
      <div className="tablewrap"><table>
        <thead><tr><th>No.</th><th>Customer / subject</th><th>Status</th><th>Priority</th><th>Branch</th><th>Owner</th><th>Time limit</th><th>Source</th><th>Created</th></tr></thead>
        <tbody>
          {(data?.items || []).map(t => (
            <tr key={t.id} className={t.overdue ? 'rowlate' : ''}>
              <td><Link to={`/complaints/${t.id}`}><b>{t.number}</b></Link></td>
              <td><div>{t.customer?.name || t.customer?.mobile || '—'} {t.urgent && <span className="pri critical">urgent</span>}</div><small className="muted">{t.subject}</small></td>
              <td><Badge status={t.status} /></td><td><Priority p={t.priority} /></td>
              <td>{t.branch || t.origin_branch || '—'}</td><td>{t.owner || '—'}</td><td><Timer t={t} /></td>
              <td>{SOURCES[t.source]}</td><td>{fmt(t.created_at)}</td>
            </tr>))}
          {data && data.items.length === 0 && <tr><td colSpan="9" className="muted pad">No complaints match.</td></tr>}
        </tbody></table></div>
      {data && <div className="row between"><small className="muted">{data.total} complaints</small>
        <div className="row"><button className="btn" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Previous</button>
          <button className="btn" disabled={page * 25 >= data.total} onClick={() => setPage(p => p + 1)}>Next</button></div></div>}
    </div>
  )
}
