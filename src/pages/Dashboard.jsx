import { Link } from 'react-router-dom'
import { api } from '../api'
import { useAuth, isBranch } from '../auth'
import { STATUS, SOURCES, useLoad, useInterval, Msg } from '../util'

const Card = ({ label, value, to, tone }) => {
  const inner = <div className={'stat ' + (tone || '')}><div className="num">{value ?? '—'}</div><div>{label}</div></div>
  return to ? <Link to={to} className="plain">{inner}</Link> : inner
}

function Bars({ data }) {
  const entries = Object.entries(data || {}); const max = Math.max(1, ...entries.map(e => e[1]))
  if (!entries.length) return <div className="muted">No data yet</div>
  return <div className="bars">{entries.map(([k, v]) => <div key={k} className="barrow"><span>{k}</span><div className="bar"><i style={{ width: (v / max * 100) + '%' }} /></div><b>{v}</b></div>)}</div>
}

export default function Dashboard() {
  const { user } = useAuth()
  const { data: d, error, reload } = useLoad(() => api('/reports/dashboard'), [])
  useInterval(reload, 60000)
  if (error) return <Msg error={error} />
  if (!d) return <div className="muted">Loading…</div>
  return (
    <div>
      <h1>Dashboard</h1>
      <div className="stats">
        <Card label="Open complaints" value={d.open} to="/complaints?open_only=true" />
        <Card label="Waiting in a queue" value={d.unassigned} to="/complaints?queue=true" />
        <Card label="Overdue (past time limit)" value={d.overdue} to="/complaints?overdue=true" tone={d.overdue ? 'bad' : ''} />
        <Card label="Assigned to me" value={d.mine} to="/complaints?mine=true" />
        {!isBranch(user) && <Card label="Repeated movement" value={d.repeated_movement} tone={d.repeated_movement ? 'bad' : ''} />}
        <Card label="Resolved on first call" value={d.first_call_resolution} />
      </div>
      <div className="grid2">
        <section className="card"><h3>Open by level</h3><Bars data={d.open_by_level} /></section>
        <section className="card"><h3>Ageing of open complaints</h3><Bars data={d.ageing} /></section>
        <section className="card"><h3>By status</h3><Bars data={Object.fromEntries(Object.entries(d.by_status).map(([k, v]) => [STATUS[k] || k, v]))} /></section>
        <section className="card"><h3>By source</h3><Bars data={Object.fromEntries(Object.entries(d.by_source).map(([k, v]) => [SOURCES[k] || k, v]))} /></section>
        <section className="card"><h3>Resolution time (hours)</h3>
          <p>Median <b>{d.resolution_hours.median ?? '—'}</b> · 90th percentile <b>{d.resolution_hours.p90 ?? '—'}</b> · {d.resolution_hours.count} resolved</p>
          <h3>Escalations</h3><p>Automatic <b>{d.escalations.automatic}</b> · Manual <b>{d.escalations.manual}</b> · Reopened <b>{d.reopened}</b></p>
        </section>
        {!isBranch(user) && <section className="card"><h3>Sent back (de-escalated) by reason</h3><Bars data={d.deescalations_by_reason} /></section>}
      </div>
      {d.branch_league && d.branch_league.length > 0 && (
        <section className="card"><h3>Branch league</h3>
          <table><thead><tr><th>Branch</th><th>Open</th><th>Resolved</th><th>Avg resolution (h)</th></tr></thead>
            <tbody>{d.branch_league.map(b => <tr key={b.branch}><td>{b.branch}</td><td>{b.open}</td><td>{b.resolved}</td><td>{b.avg_resolution_hours ?? '—'}</td></tr>)}</tbody></table>
        </section>)}
    </div>
  )
}
