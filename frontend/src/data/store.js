// Client-side data store for the prototype. Mirrors the rules in the
// backend's app/services/escalation_service.py so the demo behaves
// identically -- one level at a time, role-gated actions, full history --
// without needing a live server. State persists to localStorage so it
// survives a page refresh; "Reset demo data" below wipes it back to seed.
import { SEED_USERS, SEED_TICKETS } from './seedData'

const STORAGE_KEY = 'skyking_crm_store_v1'

const NEXT_LEVEL = { l0: 'l1', l1: 'l2', l2: 'l3' }
const STATUS_FOR_LEVEL = { l0: 'under_review', l1: 'escalated_l1', l2: 'escalated_l2', l3: 'escalated_l3' }
const ROLE_FOR_LEVEL = { l0: 'support', l1: 'l1', l2: 'l2', l3: 'l3' }
const PICKABLE_STATUSES = ['available', 'escalated_l1', 'escalated_l2', 'escalated_l3']

function loadState() {
  const raw = localStorage.getItem(STORAGE_KEY)
  if (raw) {
    try { return JSON.parse(raw) } catch { /* fall through to reseed */ }
  }
  const initial = { users: SEED_USERS, tickets: SEED_TICKETS }
  localStorage.setItem(STORAGE_KEY, JSON.stringify(initial))
  return initial
}

let state = loadState()

function persist() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
}

function findTicket(id) {
  const t = state.tickets.find(t => t.id === Number(id))
  if (!t) throw new Error('Ticket not found')
  return t
}

function findUser(id) {
  return state.users.find(u => u.id === Number(id))
}

function pushHistory(ticket, { action, prevStatus, newStatus, user, comment }) {
  ticket.history.push({
    action,
    prev_status: prevStatus,
    new_status: newStatus,
    user: user ? user.name : 'system',
    escalation_level: ticket.escalation_level,
    comment: comment || null,
    created_at: new Date().toISOString(),
  })
  ticket.updated_at = new Date().toISOString()
}

function assertCanAct(ticket, user) {
  if (user.role === 'admin') return
  const expectedRole = ROLE_FOR_LEVEL[ticket.escalation_level]
  if (user.role !== expectedRole) {
    throw new Error(`Ticket is at ${ticket.escalation_level.toUpperCase()}; only ${expectedRole.toUpperCase()} or admin may act on it`)
  }
}

export const store = {
  // ---- auth ----
  login(email, password) {
    const user = state.users.find(u => u.email.toLowerCase() === email.toLowerCase() && u.password === password)
    if (!user) throw new Error('Incorrect email or password')
    return { id: user.id, name: user.name, email: user.email, role: user.role }
  },

  // ---- tickets: list / detail ----
  listTickets({ status, escalation_level, assigned_user_id, my_tickets, priority, search, currentUserId } = {}) {
    let rows = [...state.tickets]
    if (status) rows = rows.filter(t => t.status === status)
    if (escalation_level) rows = rows.filter(t => t.escalation_level === escalation_level)
    if (assigned_user_id) rows = rows.filter(t => t.assigned_user_id === Number(assigned_user_id))
    if (my_tickets) rows = rows.filter(t => t.assigned_user_id === Number(currentUserId))
    if (priority) rows = rows.filter(t => t.priority === priority)
    if (search) {
      const q = search.toLowerCase()
      rows = rows.filter(t =>
        t.crm_code.toLowerCase().includes(q) ||
        (t.customer.name || '').toLowerCase().includes(q) ||
        (t.customer.mobile || '').toLowerCase().includes(q) ||
        String(t.msg91_ticket_id).includes(q) ||
        (t.consignment?.consignment_number || '').toLowerCase().includes(q)
      )
    }
    rows.sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
    return rows.map(t => ({
      id: t.id,
      crm_code: t.crm_code,
      msg91_ticket_id: t.msg91_ticket_id,
      customer_name: t.customer.name,
      customer_number: t.customer.mobile,
      created_at: t.created_at,
      last_message_snippet: t.last_message_snippet,
      widget_unread_count: t.widget_unread_count,
      assignee_type: 'team',
      status: t.status,
      escalation_level: t.escalation_level,
      priority: t.priority,
      assigned_user_name: t.assigned_user_id ? findUser(t.assigned_user_id)?.name : null,
      updated_at: t.updated_at,
    }))
  },

  getTicket(id) {
    const t = findTicket(id)
    return {
      id: t.id,
      crm_code: t.crm_code,
      msg91_ticket_id: t.msg91_ticket_id,
      status: t.status,
      escalation_level: t.escalation_level,
      priority: t.priority,
      issue_summary: t.issue_summary,
      comment_note: t.comment_note,
      customer: { name: t.customer.name, mobile: t.customer.mobile },
      consignment: t.consignment,
      comments: t.comments,
      history: t.history,
      msg91_last_message: t.last_message_snippet,
    }
  },

  // ---- actions ----
  pickTicket(id, user) {
    const t = findTicket(id)
    if (!PICKABLE_STATUSES.includes(t.status)) throw new Error('Ticket is not currently available to pick')
    if (t.assigned_user_id) throw new Error('Ticket already picked by another user')
    assertCanAct(t, user)

    const prevStatus = t.status
    const newStatus = t.escalation_level === 'l0' ? 'picked' : t.status
    t.status = newStatus
    t.assigned_user_id = user.id
    pushHistory(t, { action: 'picked', prevStatus, newStatus, user })
    persist()
    return t
  },

  updateDetails(id, payload) {
    const t = findTicket(id)
    if (payload.consignment_number) {
      t.consignment = {
        consignment_number: payload.consignment_number,
        address: payload.address || t.consignment?.address || '',
      }
    }
    if (payload.customer_name) t.customer.name = payload.customer_name
    if (payload.mobile_number) t.customer.mobile = payload.mobile_number
    if (payload.issue_summary !== undefined) t.issue_summary = payload.issue_summary
    if (payload.comment_note !== undefined) t.comment_note = payload.comment_note
    t.updated_at = new Date().toISOString()
    persist()
    return t
  },

  addComment(id, user, comment) {
    const t = findTicket(id)
    t.comments.push({
      user: user.name,
      level: t.escalation_level,
      comment,
      created_at: new Date().toISOString(),
    })
    pushHistory(t, { action: 'comment_added', prevStatus: t.status, newStatus: t.status, user, comment })
    persist()
    return t
  },

  escalate(id, user, reason) {
    const t = findTicket(id)
    assertCanAct(t, user)
    const targetLevel = NEXT_LEVEL[t.escalation_level]
    if (!targetLevel) throw new Error('Ticket is already at the highest escalation level (L3)')

    const prevStatus = t.status
    t.escalation_level = targetLevel
    t.status = STATUS_FOR_LEVEL[targetLevel]
    t.assigned_user_id = null
    pushHistory(t, { action: `escalated_to_${targetLevel}`, prevStatus, newStatus: t.status, user, comment: reason })
    persist()
    return t
  },

  resolve(id, user, note) {
    const t = findTicket(id)
    assertCanAct(t, user)
    const prevStatus = t.status
    t.status = 'resolved'
    t.resolved_at = new Date().toISOString()
    if (note) t.comment_note = note
    pushHistory(t, { action: 'resolved', prevStatus, newStatus: 'resolved', user, comment: note })
    persist()
    return t
  },

  close(id, user) {
    const t = findTicket(id)
    if (user.role !== 'l3' && user.role !== 'admin') throw new Error('Only L3 or Admin may close a ticket')
    if (t.status !== 'resolved') throw new Error('Only resolved tickets can be closed')
    const prevStatus = t.status
    t.status = 'closed'
    t.closed_at = new Date().toISOString()
    pushHistory(t, { action: 'closed', prevStatus, newStatus: 'closed', user })
    persist()
    return t
  },

  // ---- dashboard ----
  dashboardSummary(user) {
    const tickets = state.tickets
    const countBy = (pred) => tickets.filter(pred).length
    const today = new Date(); today.setHours(0, 0, 0, 0)

    const base = {
      total_tickets: tickets.length,
      available_tickets: countBy(t => t.status === 'available'),
      l1_tickets: countBy(t => t.status === 'escalated_l1'),
      l2_tickets: countBy(t => t.status === 'escalated_l2'),
      l3_tickets: countBy(t => t.status === 'escalated_l3'),
      resolved_today: countBy(t => t.status === 'resolved' && t.resolved_at && new Date(t.resolved_at) >= today),
      pending_tickets: countBy(t => !['resolved', 'closed'].includes(t.status)),
      critical_tickets: countBy(t => t.priority === 'critical'),
    }

    if (user.role === 'admin') return base

    if (user.role === 'support') {
      return {
        available_tickets: base.available_tickets,
        my_tickets: countBy(t => t.assigned_user_id === user.id && !['resolved', 'closed'].includes(t.status)),
        pending_tickets: base.pending_tickets,
        escalated_tickets: countBy(t => t.escalation_level !== 'l0'),
        resolved_tickets: countBy(t => t.status === 'resolved'),
      }
    }

    const levelMap = { l1: 'escalated_l1', l2: 'escalated_l2', l3: 'escalated_l3' }
    if (levelMap[user.role]) {
      return {
        waiting_at_level: countBy(t => t.status === levelMap[user.role]),
        my_tickets: countBy(t => t.assigned_user_id === user.id && t.status === levelMap[user.role]),
        resolved_tickets: base.resolved_today,
      }
    }
    return base
  },

  // ---- customers ----
  listCustomers(search = '') {
    const seen = new Map()
    for (const t of state.tickets) {
      const key = t.customer.mobile
      if (!seen.has(key)) seen.set(key, { id: key, name: t.customer.name, mobile_number: t.customer.mobile })
    }
    let rows = Array.from(seen.values())
    if (search) {
      const q = search.toLowerCase()
      rows = rows.filter(c => c.name?.toLowerCase().includes(q) || c.mobile_number?.includes(q))
    }
    return rows
  },

  getCustomer(mobile) {
    const tickets = state.tickets.filter(t => t.customer.mobile === mobile)
    const first = tickets[0]
    return {
      id: mobile,
      name: first?.customer.name,
      mobile_number: mobile,
      consignments: tickets.filter(t => t.consignment).map(t => ({
        id: t.id, consignment_number: t.consignment.consignment_number, address: t.consignment.address,
      })),
      tickets: tickets.map(t => ({ id: t.id, crm_code: t.crm_code, status: t.status, escalation_level: t.escalation_level })),
    }
  },

  // ---- demo utility ----
  resetDemoData() {
    state = { users: SEED_USERS, tickets: JSON.parse(JSON.stringify(SEED_TICKETS)) }
    persist()
  },
}
