import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import Layout from '../components/Layout'
import { store } from '../data/store'

export default function TicketDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [ticket, setTicket] = useState(null)
  const [form, setForm] = useState({})
  const [comment, setComment] = useState('')
  const [escReason, setEscReason] = useState('')
  const user = JSON.parse(localStorage.getItem('skyking_user') || 'null')

  const load = () => setTicket(store.getTicket(id))
  useEffect(load, [id])

  if (!ticket) return <Layout><div>Loading…</div></Layout>

  const nextLevel = { l0: 'L1', l1: 'L2', l2: 'L3' }[ticket.escalation_level]

  const wrap = (fn) => {
    try { fn(); load() } catch (err) { alert(err.message) }
  }

  const saveDetails = () => wrap(() => store.updateDetails(id, form))
  const submitComment = () => {
    if (!comment.trim()) return
    wrap(() => store.addComment(id, user, comment))
    setComment('')
  }
  const escalate = () => {
    if (!escReason.trim()) return alert('Reason required for escalation')
    wrap(() => store.escalate(id, user, escReason))
    setEscReason('')
  }
  const resolve = () => wrap(() => store.resolve(id, user, form.comment_note || ''))
  const close = () => wrap(() => store.close(id, user))

  const section = { background: '#fff', borderRadius: 8, padding: 20, marginBottom: 16, boxShadow: '0 1px 4px rgba(0,0,0,0.06)' }
  const label = { display: 'block', fontSize: 12, color: '#6b7280', marginBottom: 4, marginTop: 12 }
  const input = { width: '100%', padding: 8, boxSizing: 'border-box' }

  return (
    <Layout>
      <button onClick={() => navigate(-1)} style={{ marginBottom: 12, background: 'none', border: 'none', color: '#1a56db', cursor: 'pointer' }}>
        ← Back
      </button>
      <h2 style={{ marginTop: 0 }}>{ticket.crm_code} <span style={{ fontSize: 14, color: '#6b7280' }}>(MSG91 #{ticket.msg91_ticket_id})</span></h2>
      <div style={{ marginBottom: 16 }}>
        <span style={{ background: '#e0e7ff', color: '#3730a3', padding: '4px 10px', borderRadius: 12, fontSize: 12, marginRight: 8 }}>{ticket.status}</span>
        <span style={{ background: '#fef3c7', color: '#92400e', padding: '4px 10px', borderRadius: 12, fontSize: 12 }}>{ticket.escalation_level.toUpperCase()}</span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div>
          <div style={section}>
            <h4 style={{ marginTop: 0 }}>Customer / Shipment Details</h4>
            <label style={label}>Customer Name</label>
            <input style={input} defaultValue={ticket.customer?.name} onChange={e => setForm({ ...form, customer_name: e.target.value })} />
            <label style={label}>Mobile</label>
            <input style={input} defaultValue={ticket.customer?.mobile} onChange={e => setForm({ ...form, mobile_number: e.target.value })} />
            <label style={label}>Consignment Number</label>
            <input style={input} defaultValue={ticket.consignment?.consignment_number} onChange={e => setForm({ ...form, consignment_number: e.target.value })} />
            <label style={label}>Address</label>
            <input style={input} defaultValue={ticket.consignment?.address} onChange={e => setForm({ ...form, address: e.target.value })} />
            <label style={label}>Customer Issue</label>
            <textarea style={{ ...input, minHeight: 60 }} defaultValue={ticket.issue_summary} onChange={e => setForm({ ...form, issue_summary: e.target.value })} />
            <label style={label}>Comment / Note</label>
            <textarea style={{ ...input, minHeight: 60 }} defaultValue={ticket.comment_note} onChange={e => setForm({ ...form, comment_note: e.target.value })} />
            <button onClick={saveDetails} style={{ marginTop: 12, padding: '8px 16px', background: '#1a56db', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}>
              Save Details
            </button>
          </div>

          <div style={section}>
            <h4 style={{ marginTop: 0 }}>WhatsApp Conversation (latest)</h4>
            <div style={{ background: '#f0fdf4', padding: 12, borderRadius: 6, fontSize: 14, whiteSpace: 'pre-wrap' }}>
              {ticket.msg91_last_message || 'No message content available.'}
            </div>
          </div>
        </div>

        <div>
          <div style={section}>
            <h4 style={{ marginTop: 0 }}>Comments / Notes</h4>
            <div style={{ maxHeight: 200, overflowY: 'auto', marginBottom: 12 }}>
              {ticket.comments.map((c, i) => (
                <div key={i} style={{ borderBottom: '1px solid #f0f0f0', padding: '8px 0', fontSize: 13 }}>
                  <b>{c.user}</b> <span style={{ color: '#9ca3af' }}>({c.level.toUpperCase()}, {new Date(c.created_at).toLocaleString()})</span>
                  <div>{c.comment}</div>
                </div>
              ))}
              {ticket.comments.length === 0 && <div style={{ color: '#9ca3af', fontSize: 13 }}>No comments yet.</div>}
            </div>
            <textarea style={{ ...input, minHeight: 50 }} placeholder="Add a comment…" value={comment} onChange={e => setComment(e.target.value)} />
            <button onClick={submitComment} style={{ marginTop: 8, padding: '6px 14px', background: '#374151', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}>
              Add Comment
            </button>
          </div>

          <div style={section}>
            <h4 style={{ marginTop: 0 }}>Actions</h4>
            {ticket.status !== 'resolved' && ticket.status !== 'closed' && (
              <>
                <button onClick={resolve} style={{ padding: '8px 16px', background: '#16a34a', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', marginRight: 8 }}>
                  Resolve Ticket
                </button>
                {nextLevel && (
                  <>
                    <label style={label}>Escalate to {nextLevel} — reason</label>
                    <input style={input} value={escReason} onChange={e => setEscReason(e.target.value)} placeholder="Why is this being escalated?" />
                    <button onClick={escalate} style={{ marginTop: 8, padding: '8px 16px', background: '#ea580c', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}>
                      Escalate to {nextLevel}
                    </button>
                  </>
                )}
              </>
            )}
            {ticket.status === 'resolved' && (
              <button onClick={close} style={{ padding: '8px 16px', background: '#111827', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}>
                Close Ticket (L3/Admin)
              </button>
            )}
          </div>

          <div style={section}>
            <h4 style={{ marginTop: 0 }}>Ticket History</h4>
            <div style={{ maxHeight: 260, overflowY: 'auto' }}>
              {ticket.history.map((h, i) => (
                <div key={i} style={{ fontSize: 12, borderLeft: '2px solid #1a56db', paddingLeft: 10, marginBottom: 10 }}>
                  <div style={{ color: '#9ca3af' }}>{new Date(h.created_at).toLocaleString()}</div>
                  <div><b>{h.user}</b> → {h.action.replace(/_/g, ' ')}</div>
                  {h.comment && <div style={{ color: '#4b5563' }}>{h.comment}</div>}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </Layout>
  )
}
