import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../components/Layout'
import { store } from '../data/store'

const QUEUE_CONFIG = {
  available: { status: 'available', title: 'Available Tickets' },
  mine: { my_tickets: true, title: 'My Tickets' },
  l1: { escalation_level: 'l1', title: 'L1 Escalations' },
  l2: { escalation_level: 'l2', title: 'L2 Escalations' },
  l3: { escalation_level: 'l3', title: 'L3 Escalations' },
  resolved: { status: 'resolved', title: 'Resolved Tickets' },
}

export default function TicketList({ queue }) {
  const [tickets, setTickets] = useState([])
  const [search, setSearch] = useState('')
  const navigate = useNavigate()
  const cfg = QUEUE_CONFIG[queue]
  const user = JSON.parse(localStorage.getItem('skyking_user') || 'null')

  const load = () => {
    const params = { ...cfg, search, currentUserId: user?.id }
    delete params.title
    setTickets(store.listTickets(params))
  }

  useEffect(load, [queue, search])

  const pick = (id, e) => {
    e.stopPropagation()
    try {
      store.pickTicket(id, user)
      load()
    } catch (err) {
      alert(err.message)
    }
  }

  const priorityColor = { critical: '#dc2626', high: '#ea580c', medium: '#ca8a04', low: '#65a30d' }

  return (
    <Layout>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>{cfg.title}</h2>
        <input placeholder="Search ticket / customer / mobile / consignment"
          value={search} onChange={e => setSearch(e.target.value)}
          style={{ padding: 8, width: 320 }} />
      </div>

      <div style={{ background: '#fff', borderRadius: 8, overflow: 'hidden', boxShadow: '0 1px 4px rgba(0,0,0,0.06)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
          <thead>
            <tr style={{ background: '#f9fafb', textAlign: 'left' }}>
              <th style={th}>Ticket</th>
              <th style={th}>Customer</th>
              <th style={th}>Mobile</th>
              <th style={th}>Last Message</th>
              <th style={th}>Unread</th>
              <th style={th}>Status</th>
              <th style={th}>Level</th>
              <th style={th}>Priority</th>
              <th style={th}>Assigned</th>
              <th style={th}></th>
            </tr>
          </thead>
          <tbody>
            {tickets.map(t => (
              <tr key={t.id} onClick={() => navigate(`/tickets/${t.id}`)} style={{ cursor: 'pointer', borderTop: '1px solid #f0f0f0' }}>
                <td style={td}>{t.crm_code}</td>
                <td style={td}>{t.customer_name || '—'}</td>
                <td style={td}>{t.customer_number}</td>
                <td style={{ ...td, maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {t.last_message_snippet}
                </td>
                <td style={td}>{t.widget_unread_count > 0 ? <span style={{ background: '#dc2626', color: '#fff', borderRadius: 10, padding: '2px 8px', fontSize: 12 }}>{t.widget_unread_count}</span> : '—'}</td>
                <td style={td}>{t.status}</td>
                <td style={td}>{t.escalation_level.toUpperCase()}</td>
                <td style={{ ...td, color: priorityColor[t.priority], fontWeight: 600 }}>{t.priority}</td>
                <td style={td}>{t.assigned_user_name || '—'}</td>
                <td style={td}>
                  {(t.status === 'available' || (t.escalation_level !== 'l0' && !t.assigned_user_name && t.status.startsWith('escalated'))) && (
                    <button onClick={(e) => pick(t.id, e)} style={{ padding: '6px 12px', background: '#16a34a', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}>
                      Pick Ticket
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {tickets.length === 0 && (
              <tr><td style={td} colSpan={10}>No tickets in this queue.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </Layout>
  )
}

const th = { padding: '10px 14px', color: '#6b7280', fontWeight: 600, fontSize: 12, textTransform: 'uppercase' }
const td = { padding: '10px 14px' }
