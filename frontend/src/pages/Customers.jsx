import { useEffect, useState } from 'react'
import Layout from '../components/Layout'
import { store } from '../data/store'

export default function Customers() {
  const [search, setSearch] = useState('')
  const [customers, setCustomers] = useState([])
  const [selected, setSelected] = useState(null)

  useEffect(() => { setCustomers(store.listCustomers(search)) }, [search])

  const open = (id) => setSelected(store.getCustomer(id))

  return (
    <Layout>
      <h2>Customers</h2>
      <input placeholder="Search by name or mobile" value={search} onChange={e => setSearch(e.target.value)}
        style={{ padding: 8, width: 320, marginBottom: 16 }} />
      <div style={{ display: 'flex', gap: 16 }}>
        <div style={{ flex: 1, background: '#fff', borderRadius: 8, padding: 12 }}>
          {customers.map(c => (
            <div key={c.id} onClick={() => open(c.id)} style={{ padding: 10, cursor: 'pointer', borderBottom: '1px solid #f0f0f0' }}>
              <b>{c.name}</b><br /><span style={{ color: '#6b7280', fontSize: 13 }}>{c.mobile_number}</span>
            </div>
          ))}
          {customers.length === 0 && <div style={{ color: '#9ca3af', padding: 10 }}>No customers found.</div>}
        </div>
        {selected && (
          <div style={{ flex: 1, background: '#fff', borderRadius: 8, padding: 16 }}>
            <h3>{selected.name}</h3>
            <div style={{ color: '#6b7280' }}>{selected.mobile_number}</div>
            <h4>Tickets</h4>
            {selected.tickets.map(t => (
              <div key={t.id}>{t.crm_code} — {t.status} ({t.escalation_level.toUpperCase()})</div>
            ))}
            <h4>Consignments</h4>
            {selected.consignments.length === 0 && <div style={{ color: '#9ca3af', fontSize: 13 }}>None recorded yet.</div>}
            {selected.consignments.map(c => (
              <div key={c.id}>{c.consignment_number} — {c.address}</div>
            ))}
          </div>
        )}
      </div>
    </Layout>
  )
}
