import { useState } from 'react'
import { api } from '../api'
import { useLoad, Msg } from '../util'

export default function Branches() {
  const { data, error, reload } = useLoad(() => api('/branches'), [])
  const { data: regions } = useLoad(() => api('/regions'), [])
  const [f, setF] = useState({ code: '', name: '', city: '', state: '', region_id: '', pincodes: '' }), [err, setErr] = useState(''), [ok, setOk] = useState('')
  const set = (k, v) => setF(x => ({ ...x, [k]: v }))
  const add = async e => {
    e.preventDefault(); setErr(''); setOk('')
    try {
      await api('/branches', { method: 'POST', body: { ...f, region_id: f.region_id ? +f.region_id : null, pincodes: f.pincodes.split(/[,;\s]+/).filter(Boolean) } })
      setF({ code: '', name: '', city: '', state: '', region_id: '', pincodes: '' }); setOk('Branch created. Invite its Branch Admin, then set it Live.'); reload()
    } catch (x) { setErr(x.message) }
  }
  const status = async (b, s) => { setErr(''); try { const r = await api('/branches/' + b.id, { method: 'PATCH', body: { status: s } }); setOk(s === 'suspended' ? `${r.tickets_returned} complaint(s) returned to L2` : 'Updated'); reload() } catch (x) { setErr(x.message) } }
  const importCsv = async e => {
    const file = e.target.files[0]; if (!file) return; const fd = new FormData(); fd.append('file', file); setErr(''); setOk('')
    try { const r = await api('/branches/import', { method: 'POST', body: fd }); setOk(`Imported: ${r.created} new, ${r.updated} updated` + (r.errors.length ? `. ${r.errors.length} row(s) skipped: ` + r.errors.map(x => `row ${x.row} (${x.error})`).join('; ') : '')); reload() } catch (x) { setErr(x.message) }
    e.target.value = ''
  }
  return (
    <div>
      <h1>Branches</h1>
      <Msg error={error || err} ok={ok} />
      <div className="tablewrap"><table><thead><tr><th>Code</th><th>Branch</th><th>City</th><th>Region</th><th>Pincodes served</th><th>Status</th><th></th></tr></thead>
        <tbody>{(data || []).map(b => <tr key={b.id}><td><b>{b.code}</b></td><td>{b.name}</td><td>{b.city}</td><td>{b.region || '—'}</td><td>{b.pincodes.join(', ') || '—'}</td>
          <td><span className={'badge ' + (b.status === 'live' ? 'ok' : b.status === 'suspended' ? 'hot' : 'wait')}>{b.status}</span></td>
          <td className="row">{b.status !== 'live' && <button className="btn" onClick={() => status(b, 'live')}>Go live</button>}
            {b.status === 'live' && <button className="btn" onClick={() => window.confirm('Suspend this branch? Its open complaints go back to L2.') && status(b, 'suspended')}>Suspend</button>}</td></tr>)}</tbody></table></div>
      <div className="grid2">
        <form className="card form" onSubmit={add}><h3>Add a branch</h3>
          <div className="two"><label>Code *<input value={f.code} onChange={e => set('code', e.target.value)} /></label><label>Name *<input value={f.name} onChange={e => set('name', e.target.value)} /></label></div>
          <div className="two"><label>City<input value={f.city} onChange={e => set('city', e.target.value)} /></label><label>State<input value={f.state} onChange={e => set('state', e.target.value)} /></label></div>
          <label>Region<select value={f.region_id} onChange={e => set('region_id', e.target.value)}><option value="">—</option>{(regions || []).map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></label>
          <label>Pincodes served (comma separated)<input value={f.pincodes} onChange={e => set('pincodes', e.target.value)} /></label>
          <button className="btn primary" disabled={!f.code || !f.name}>Create branch</button></form>
        <div className="card"><h3>Bulk import</h3><p className="muted">CSV columns: code, name, city, state, region, address, contact_name, contact_email, contact_phone, pincodes (separate pincodes with ;). New regions are created automatically.</p>
          <input type="file" accept=".csv" onChange={importCsv} /></div>
      </div>
    </div>
  )
}
