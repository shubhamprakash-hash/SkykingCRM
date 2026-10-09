// In-browser demo engine: the same rules as the real backend (states, levels, SLA timers, de-escalation,
// branch scoping) running on localStorage so the prototype works on a static host with no server.
// PROTOTYPE ONLY: no real security (plain passwords, data stays in the visitor's browser).
const KEY = 'sk_demo_v2', SESS = 'sk_demo_session', PW = 'demo1234'
export const DEMO_PASSWORD = PW
const store = (() => { try { localStorage.setItem('_t', '1'); localStorage.removeItem('_t'); return localStorage } catch { const m = {}; return { getItem: k => m[k] ?? null, setItem: (k, v) => { m[k] = v }, removeItem: k => { delete m[k] } } } })()
let DB = null
const T = () => Date.now() + (DB?.offset || 0)
const save = () => store.setItem(KEY, JSON.stringify(DB))
const KEEP = Symbol('keep')
const MIN = 60000
class Err extends Error { constructor(m, status = 400, data = {}) { super(m); this.status = status; this.data = { detail: m, ...data } } }
const chk = (c, m = 'Not allowed') => { if (!c) throw new Err(m, 403) }
const bad = m => { throw new Err(m, 422) }
const iso = ms => ms ? new Date(ms).toISOString() : null

// ------------------------------------------------------------------ enums / tables
const S = { DRAFT: 'DRAFT', L1Q: 'L1_QUEUE', L1W: 'L1_WORKING', L2Q: 'L2_QUEUE', L2W: 'L2_WORKING', AB: 'ASSIGNED_BRANCH', BA: 'BRANCH_ACK', AT: 'ACTION_TAKEN', L3Q: 'L3_QUEUE', L3W: 'L3_WORKING', AC: 'AWAITING_CUSTOMER', ABI: 'AWAITING_BRANCH_INFO', RES: 'RESOLVED', CL: 'CLOSED' }
const QUEUE = { 1: S.L1Q, 2: S.L2Q, 3: S.L3Q }, WORKING = { 1: S.L1W, 2: S.L2W, 3: S.L3W }
const LEVEL_OF = { L1_QUEUE: 1, L1_WORKING: 1, L2_QUEUE: 2, L2_WORKING: 2, ASSIGNED_BRANCH: 2, BRANCH_ACK: 2, ACTION_TAKEN: 2, L3_QUEUE: 3, L3_WORKING: 3 }
const BRANCH_PHASE = [S.AB, S.BA, S.AT], PAUSED = [S.AC, S.ABI]
const ALL = Object.values(S)
const OPEN = ALL.filter(s => ![S.DRAFT, S.RES, S.CL].includes(s))
const ALLOWED = {
  DRAFT: [S.L1Q], L1_QUEUE: [S.L1W, S.L2Q, S.RES, S.AC, S.ABI, S.DRAFT], L1_WORKING: [S.L1Q, S.L2Q, S.RES, S.AC, S.ABI],
  L2_QUEUE: [S.L2W, S.L3Q, S.L1Q, S.L1W, S.AB, S.RES, S.AC], L2_WORKING: [S.L2Q, S.L3Q, S.L1Q, S.L1W, S.AB, S.RES, S.AC],
  ASSIGNED_BRANCH: [S.AB, S.BA, S.AT, S.L3Q, S.L2Q, S.L1Q, S.L1W, S.RES, S.AC], BRANCH_ACK: [S.AB, S.AT, S.L3Q, S.L2Q, S.L1Q, S.L1W, S.RES, S.AC],
  ACTION_TAKEN: [S.RES, S.AB, S.L3Q, S.L1Q, S.L1W], L3_QUEUE: [S.L3W, S.L2Q, S.L2W, S.RES, S.AC], L3_WORKING: [S.L3Q, S.L2Q, S.L2W, S.RES, S.AC],
  AWAITING_CUSTOMER: [...OPEN.filter(s => s !== S.AC && s !== S.ABI), S.RES], AWAITING_BRANCH_INFO: [S.L1Q, S.L1W, S.RES], RESOLVED: [S.CL, S.L1Q, S.L2Q, S.L3Q], CLOSED: [S.L1Q, S.L2Q, S.L3Q],
}
const REASONS = ['escalated_too_early', 'more_information_needed', 'wrong_category_or_branch', 'action_needed_at_lower_level', 'decision_taken_needs_execution', 'priority_reduced', 'other']
const PRI = ['low', 'medium', 'high', 'critical']

// ------------------------------------------------------------------ working-hours clock (IST, no DST)
const IST = 330 * MIN
const part = ms => { const d = new Date(ms + IST); return { day: (d.getUTCDay() + 6) % 7, mins: d.getUTCHours() * 60 + d.getUTCMinutes(), date: d.toISOString().slice(0, 10) } }
const nextMidnight = ms => ms - ((ms + IST) % 86400000) + 86400000
const hm = s => { const [h, m] = s.split(':'); return +h * 60 + +m }
function addWorking(ms, min, cal = DB.calendar) {
  if (cal.mode === '24x7') return ms + min * MIN
  const open = hm(cal.start), close = hm(cal.end); let cur = ms, rem = min
  for (let i = 0; i < 800; i++) {
    const p = part(cur)
    if (!cal.days.includes(p.day) || cal.holidays.includes(p.date) || p.mins >= close) { cur = nextMidnight(cur); continue }
    if (p.mins < open) { cur += (open - p.mins) * MIN; continue }
    const avail = close - p.mins
    if (rem <= avail) return cur + rem * MIN
    rem -= avail; cur += avail * MIN
  }
  return ms + min * MIN
}
function workingBetween(a, b, cal = DB.calendar) {
  if (b <= a) return 0
  if (cal.mode === '24x7') return Math.floor((b - a) / MIN)
  const open = hm(cal.start), close = hm(cal.end); let cur = a, tot = 0
  for (let i = 0; i < 2000 && cur < b; i++) {
    const p = part(cur)
    if (!cal.days.includes(p.day) || cal.holidays.includes(p.date) || p.mins >= close) { cur = nextMidnight(cur); continue }
    if (p.mins < open) { cur += (open - p.mins) * MIN; continue }
    const end = Math.min(cur + (close - p.mins) * MIN, b); tot += (end - cur) / MIN; cur = end
  }
  return Math.floor(tot)
}

// ------------------------------------------------------------------ helpers
const isAdmin = u => u && ['SUPER_ADMIN', 'HO_ADMIN'].includes(u.role)
const lvlOf = u => ({ L1: 1, L2: 2, L3: 3 })[u?.role]
const isBranch = u => u && ['BRANCH_ADMIN', 'BRANCH_STAFF'].includes(u.role)
const isHO = u => u && (lvlOf(u) || isAdmin(u))
const atLevel = (u, t) => isAdmin(u) || lvlOf(u) === t.level
const user = id => DB.users.find(x => x.id === id)
const branchOf = id => DB.branches.find(x => x.id === id)
const tkt = id => DB.tickets.find(x => x.id === +id)
const nid = k => (DB.ids[k] = (DB.ids[k] || 0) + 1)
const normMobile = m => { if (!m) return null; let d = String(m).replace(/\D/g, ''); if (d.length === 12 && d.startsWith('91')) d = d.slice(2); if (d.length === 11 && d.startsWith('0')) d = d.slice(1); return d || null }
const threshold = (lvl, p) => DB.policies[`${lvl}:${p}`] ?? (p === 'critical' ? DB.rules.critical_minutes : DB.rules.default_minutes)
const actsOnClock = (u, t) => BRANCH_PHASE.slice(0, 2).includes(t.status) ? (isBranch(u) && u.branch_id === t.branch_id) : (isAdmin(u) || lvlOf(u) === t.level)

function notify(ids, text, t, kind = 'info') { for (const id of new Set(ids.filter(Boolean))) DB.notifications.push({ id: nid('n'), user_id: id, ticket_id: t?.id ?? null, kind, text, at: T(), read: false }) }
const toLevel = (lvl, text, t, kind, leads) => notify(DB.users.filter(u => u.role === 'L' + lvl && u.status === 'active' && (!leads || u.is_team_lead)).map(u => u.id), text, t, kind)
const toAdmins = (text, t, kind = 'alert') => notify(DB.users.filter(u => isAdmin(u) && u.status === 'active').map(u => u.id), text, t, kind)
const toBranch = (bid, text, t, kind, adminsOnly) => bid && notify(DB.users.filter(u => u.branch_id === bid && u.status === 'active' && (!adminsOnly || u.role === 'BRANCH_ADMIN')).map(u => u.id), text, t, kind)

function arm(t, now, minutes) {
  const s = t.status, r = DB.rules
  if (LEVEL_OF[s] && ![S.AB, S.BA].includes(s)) t.due_at = addWorking(now, minutes ?? threshold(LEVEL_OF[s], t.priority))
  else if ([S.AB, S.BA].includes(s)) t.due_at = addWorking(now, minutes ?? t.branch_deadline_minutes ?? r.branch_deadline_default)
  else if (s === S.ABI) t.due_at = addWorking(now, minutes ?? r.info_limit_minutes)
  else if (s === S.RES) t.due_at = now + r.auto_close_hours * 3600000
  else t.due_at = null
  t.warned_at = null; t.last_activity_at = now
}
function log(t, type, actor, o = {}, now = T()) {
  t.events.push({ id: nid('e'), at: now, actor_id: actor?.id ?? null, actor_type: o.actor_type || (actor ? 'user' : 'system'), type, from_status: o.from?.[0] ?? null, to_status: o.to?.[0] ?? t.status,
    from_level: o.from?.[1] ?? null, to_level: o.to?.[1] ?? t.level, trigger: o.trigger ?? null, reason_code: o.reason_code ?? null, reason: o.reason ?? null, note: o.note ?? null, meta: o.meta ?? null })
}
function move(t, to, now, { level, via } = {}) {
  const old = t.status
  if (via === 'merge') { if (!(OPEN.includes(old) || old === S.RES) || to !== S.CL) throw new Err('merge not allowed', 409) }
  else if (via !== 'admin_force') {
    if (old === null) { if (![S.DRAFT, S.L1Q, S.L2Q, S.L3Q].includes(to)) throw new Err('cannot create there', 409) }
    else if (!(ALLOWED[old] || []).includes(to)) throw new Err(`Move ${old} -> ${to} is not allowed`, 409)
  }
  const lv = LEVEL_OF[to], prev = [old, t.level]
  const nl = lv ?? (to === S.DRAFT ? null : (level ?? t.level))
  const ol = t.level; t.status = to; t.level = nl
  if (nl !== ol) { t.level_entered_at = now; if (ol != null && nl != null) t.moves_count = (t.moves_count || 0) + 1 }
  return prev
}
function transition(t, actor, type, to, now, o = {}) {
  const prev = move(t, to, now, o)
  if (o.owner !== undefined && o.owner !== KEEP) t.owner_id = o.owner
  if (o.rearm !== false) arm(t, now, o.minutes)
  log(t, type, actor, { from: prev, trigger: o.trigger ?? 'manual', reason_code: o.reason_code, reason: o.reason, note: o.note, meta: o.meta, actor_type: o.actor_type }, now)
  if ((t.moves_count || 0) >= DB.rules.repeated_movement_at && !t.repeated_movement) { t.repeated_movement = true; toAdmins(`${t.number}: repeated movement between levels`, t); toLevel(t.level || 1, `${t.number}: repeated movement between levels`, t, 'alert', true) }
  t.version++
}
function touch(t, actor, now) {
  if (!actor || !actsOnClock(actor, t)) return
  if (t.cooling && lvlOf(actor) === t.level) t.cooling = false
  if ((LEVEL_OF[t.status] || t.status === S.ABI) && t.status !== S.ABI) arm(t, now)
}
const text = (v, name, n = 1) => { v = (v || '').trim(); if (v.length < n) bad(`${name} is required (at least ${n} characters)`); return v }
const rememberOwner = (t, lvl, id) => { t.prev_owner = { ...(t.prev_owner || {}), [lvl]: id } }
const incomplete = t => !(t.consignment_no && t.pincode)
const toCustomer = (t, body) => DB.outbox.push({ t: t.id, body })

// ------------------------------------------------------------------ visibility
function canSee(u, t) {
  if (isAdmin(u)) return true
  if (lvlOf(u)) return t.status !== S.DRAFT
  if (u.role === 'REGIONAL_MANAGER') { const ids = DB.branches.filter(b => b.region_id === u.region_id).map(b => b.id); return t.status !== S.DRAFT && (ids.includes(t.branch_id) || ids.includes(t.origin_branch_id)) }
  if (isBranch(u)) return [t.branch_id, t.origin_branch_id].includes(u.branch_id) || (t.tb || []).includes(u.branch_id)
  return false
}
const branchCanWrite = (u, t) => isBranch(u) && [t.branch_id, t.origin_branch_id].includes(u.branch_id) && t.status !== S.CL

// ------------------------------------------------------------------ create
function findCustomer(mobile, email) {
  const m = normMobile(mobile)
  return (m && DB.customers.find(c => c.mobile === m)) || (email && DB.customers.find(c => c.email === email.trim().toLowerCase())) || null
}
export function createTicket(creator, d, now = T()) {
  d = { mode: 'queue', source: creator && isBranch(creator) ? 'branch' : 'phone_inbound', ...d }
  if (!['whatsapp', 'email', 'phone_inbound', 'phone_callback', 'walk_in', 'branch', 'other'].includes(d.source)) bad('unknown source')
  d.description = text(d.description, 'Description', 3)
  if (creator && isBranch(creator)) { if (branchOf(creator.branch_id).status !== 'live') chk(false, 'Your branch is not live yet'); d.source = 'branch' }
  else if (creator && !isHO(creator)) chk(false, 'This role cannot create complaints')
  if (creator && d.mode !== 'draft') { if (!normMobile(d.mobile) && !d.email) bad('Customer mobile (or email) is required'); if (!d.category_id) bad('Category is required') }
  let c = findCustomer(d.mobile, d.email)
  if (!c && (normMobile(d.mobile) || d.email)) { c = { id: nid('c'), name: d.name || null, mobile: normMobile(d.mobile), email: (d.email || '').trim().toLowerCase() || null }; DB.customers.push(c) }
  else if (c && d.name && !c.name) c.name = d.name
  const dups = c && d.consignment_no ? DB.tickets.filter(t => t.customer_id === c.id && t.consignment_no === d.consignment_no && OPEN.includes(t.status)) : []
  if (dups.length && !d.allow_duplicate) throw new Err('An open complaint already exists for this customer and consignment', 409, { numbers: dups.map(x => x.number), ticket_ids: dups.map(x => x.id) })
  const cat = DB.categories.find(x => x.id === d.category_id)
  let pr = d.priority || cat?.default_priority || 'medium'; if (!PRI.includes(pr)) bad('invalid priority')
  if (d.urgent && PRI.indexOf(pr) < 2) pr = 'high'
  const t = { id: nid('t'), number: 'CRM-' + String(nid('num')).padStart(7, '0'), source: d.source, customer_id: c?.id ?? null, category_id: d.category_id || null, subject: d.subject || d.description.slice(0, 80),
    description: d.description, priority: pr, urgent: !!d.urgent, status: null, level: null, owner_id: null, branch_id: null, branch_assignee_id: null, origin_branch_id: null,
    consignment_no: d.consignment_no || null, receiver_name: d.receiver_name || null, receiver_mobile: normMobile(d.receiver_mobile), address: d.address || null, pincode: d.pincode || null,
    preferred_contact: null, preferred_language: d.preferred_language || null, caller_number: normMobile(d.caller_number), call_received_at: d.call_received_at || null, call_reference: d.call_reference || null,
    created_at: now, forwarded_at: null, level_entered_at: null, last_activity_at: null, due_at: null, warned_at: null, remaining_minutes: null, paused_from: null, branch_deadline_minutes: null,
    extension_count: 0, cooling: false, escalation_count: 0, deescalation_count: 0, moves_count: 0, repeated_movement: false, prev_owner: {}, resolved_at: null, resolved_level: null, closed_at: null,
    reopen_count: 0, resolution: null, version: 1, events: [], messages: [], attachments: [], tb: [], merged_into_id: null }
  t.incomplete = incomplete(t)
  let target, lvl
  if (creator && isBranch(creator)) { t.origin_branch_id = creator.branch_id; [target, lvl] = d.mode === 'draft' ? [S.DRAFT, null] : [S.L1Q, 1] }
  else { lvl = d.level || (creator && !isAdmin(creator) ? lvlOf(creator) : 1) || 1; target = QUEUE[lvl] }
  DB.tickets.push(t)
  transition(t, creator, 'created', target, now, { level: lvl, trigger: creator ? 'manual' : 'system', meta: { source: t.source, mode: d.mode, incomplete: t.incomplete }, rearm: target !== S.DRAFT })
  if (target === S.L1Q && creator && isBranch(creator)) { t.forwarded_at = now; log(t, 'forwarded', creator, { note: 'Registered and forwarded to Head Office' }, now) }
  if (target !== S.DRAFT) {
    toCustomer(t, `We have registered your complaint ${t.number}.`)
    if (t.urgent) { toLevel(1, `URGENT: ${t.number} registered by a branch`, t, 'alert', true); toLevel(2, `URGENT: ${t.number} registered by a branch`, t, 'alert', true) }
  }
  if (d.mode === 'take' && creator && !isBranch(creator) && target !== S.DRAFT) A.pick.run(t, creator, {}, now)
  if (d.resolve) A.resolve.run(t, creator, { ...d.resolve, first_call: true }, now)
  return t
}

// ------------------------------------------------------------------ actions: pre (permission+state) / run
const qOrW = lv => [QUEUE[lv], WORKING[lv]]
const bUser = (u, t) => isBranch(u) && t.branch_id != null && u.branch_id === t.branch_id
const A = {}
const def = (name, pre, run) => { A[name] = { pre, run } }
def('pick', (t, u) => { chk(Object.values(QUEUE).includes(t.status) && !t.owner_id, 'Complaint is not waiting in a queue'); chk(!isBranch(u) && atLevel(u, t), 'Only the owning level can pick this complaint') },
  (t, u, p, now) => { A.pick.pre(t, u); const l = t.level; transition(t, u, 'picked', WORKING[l], now, { owner: u.id }); rememberOwner(t, l, u.id); touch(t, u, now) })
def('release', (t, u) => { chk(Object.values(WORKING).includes(t.status), 'Complaint is not being worked'); chk(t.owner_id === u.id || isAdmin(u) || (u.is_team_lead && lvlOf(u) === t.level), 'Only the owner can release') },
  (t, u, p, now) => { transition(t, u, 'released', QUEUE[t.level], now, { owner: null }) })
def('escalate', (t, u) => { chk(!isBranch(u) && [1, 2].includes(t.level), 'Only L1 and L2 can escalate'); chk([...qOrW(t.level), ...(t.level === 2 ? BRANCH_PHASE : [])].includes(t.status), 'Cannot escalate from this status'); chk(isAdmin(u) || lvlOf(u) === t.level, 'Only the current level can escalate'); chk(!t.cooling || isAdmin(u), 'This complaint was just sent back: log an action before escalating it again') },
  (t, u, p, now) => { const reason = text(p.reason, 'Reason', 3), f = t.level; transition(t, u, 'escalated', QUEUE[f + 1], now, { owner: null, trigger: f === 2 ? 'l2_direct' : 'manual', reason }); t.escalation_count++; t.cooling = false; toLevel(f + 1, `${t.number} escalated to L${f + 1}: ${reason}`, t, 'escalation') })
def('deescalate', (t, u) => { chk(!isBranch(u) && [2, 3].includes(t.level), 'Only L2 and L3 can send a complaint back'); chk(OPEN.includes(t.status) && !PAUSED.includes(t.status), 'Cannot be sent back in this status'); chk(isAdmin(u) || lvlOf(u) === t.level, 'Only the current level can send it back') },
  (t, u, p, now) => {
    const c = DB.rules
    if (!REASONS.includes(p.reason_code)) bad('Choose a valid reason')
    const note = text(p.note, 'Handover note', c.min_handover_chars)
    if (p.skip && !(isAdmin(u) && t.level === 3)) chk(false, 'Only Admin can skip a level')
    if (t.deescalation_count >= c.max_deescalations && !isAdmin(u)) chk(false, 'Send-back limit reached: Admin approval is needed')
    const f = t.level, target = p.skip ? 1 : f - 1, hadBranch = t.branch_id != null
    if (f === 2 && hadBranch) { if (p.withdraw_branch == null) bad('Choose whether to withdraw the branch assignment or keep it'); if (p.withdraw_branch) { toBranch(t.branch_id, `${t.number}: assignment withdrawn by Head Office (thread is now read-only)`, t); t.branch_id = null; t.branch_assignee_id = null } }
    let owner = null, ns = QUEUE[target]
    if (p.target_user_id) { const tu = user(p.target_user_id); if (!tu || tu.status !== 'active' || lvlOf(tu) !== target) bad(`Choose an active L${target} user`); owner = tu.id; ns = WORKING[target] }
    else if (!p.skip) { const pu = user((t.prev_owner || {})[target]); if (pu && pu.status === 'active' && lvlOf(pu) === target) { owner = pu.id; ns = WORKING[target] } }
    transition(t, u, 'deescalated', ns, now, { owner, trigger: 'deescalate', reason_code: p.reason_code, note, meta: { skip: !!p.skip }, via: p.skip ? 'admin_force' : undefined })
    t.deescalation_count++; t.cooling = true; if (owner) rememberOwner(t, target, owner)
    const msg = `${t.number} sent back to L${target} from L${f}: ${note.slice(0, 120)}`; toLevel(target, msg, t, 'deescalation', true); notify([owner], msg, t, 'deescalation')
  })
def('assign_branch', (t, u) => { chk(!isBranch(u) && (isAdmin(u) || lvlOf(u) === 2), 'Only L2 can assign to a branch'); chk(t.level === 2 && [S.L2Q, S.L2W, S.AB, S.BA].includes(t.status), 'Complaint is not at L2') },
  (t, u, p, now) => {
    const c = DB.rules, br = branchOf(+p.branch_id); if (!br) throw new Err('Branch not found', 404); if (br.status !== 'live') bad('Branch is not live')
    if (incomplete(t)) bad('Complete the consignment number and pincode before assigning to a branch')
    const dl = p.deadline_minutes || c.branch_deadline_default; if (dl < c.branch_deadline_min || dl > c.branch_deadline_max) bad(`Deadline must be between ${c.branch_deadline_min} and ${c.branch_deadline_max} minutes`)
    const old = t.branch_id; t.branch_id = br.id; t.branch_assignee_id = p.assignee_id || null; t.branch_deadline_minutes = dl; t.extension_count = 0
    t.tb = [...new Set([...(t.tb || []), br.id])]
    transition(t, u, 'assigned_branch', S.AB, now, { owner: t.owner_id || (lvlOf(u) === 2 ? u.id : null), meta: { branch: br.code, deadline_minutes: dl, reassigned_from: old } }); t.cooling = false
    toBranch(br.id, `${t.number} assigned to ${br.name}. Deadline: ${Math.floor(dl / 60)}h ${dl % 60}m`, t, 'assignment'); if (old && old !== br.id) toBranch(old, `${t.number} was moved to another branch`, t)
  })
def('extend_deadline', (t, u) => { chk(!isBranch(u) && (isAdmin(u) || lvlOf(u) === 2), 'Only L2 can extend a branch deadline'); chk([S.AB, S.BA].includes(t.status) && t.due_at, 'No branch deadline to extend'); chk(t.due_at > T(), 'The deadline has already passed') },
  (t, u, p, now) => {
    A.extend_deadline.pre(t, u); if (t.extension_count >= DB.rules.max_extensions) bad('Extension limit reached for this complaint')
    const m = +p.minutes; if (!(m >= 30 && m <= 1440)) bad('Extension must be 30 to 1440 minutes'); const reason = text(p.reason, 'Reason', 3)
    const before = t.due_at; t.due_at = addWorking(before, m); t.warned_at = null; t.extension_count++; log(t, 'deadline_extended', u, { from: [t.status, t.level], reason, meta: { minutes: m } }, now); toBranch(t.branch_id, `${t.number}: deadline extended`, t); t.version++
  })
def('branch_ack', (t, u) => chk(bUser(u, t) && t.status === S.AB, 'Nothing to acknowledge'), (t, u, p, now) => { transition(t, u, 'branch_acknowledged', S.BA, now); notify([t.owner_id], `${t.number} acknowledged by branch`, t) })
def('branch_action_taken', (t, u) => chk(bUser(u, t) && [S.AB, S.BA].includes(t.status), 'Nothing to update'),
  (t, u, p, now) => { const n = text(p.notes, 'Action taken', 10); transition(t, u, 'action_taken', S.AT, now, { note: n }); t.owner_id ? notify([t.owner_id], `${t.number}: branch reports action taken - please verify`, t, 'verify') : toLevel(2, `${t.number}: branch reports action taken - please verify`, t, 'verify') })
def('branch_return', (t, u) => chk(bUser(u, t) && [S.AB, S.BA].includes(t.status), 'Nothing to return'),
  (t, u, p, now) => { const r = text(p.reason, 'Reason', 5); t.branch_id = null; t.branch_assignee_id = null; transition(t, u, 'branch_return', S.L2Q, now, { owner: null, trigger: 'branch_return', reason: r }); toLevel(2, `${t.number} returned by branch: ${r}`, t, 'branch_return') })
def('branch_distribute', (t, u) => chk(u.role === 'BRANCH_ADMIN' && bUser(u, t) && BRANCH_PHASE.includes(t.status), 'Not allowed'),
  (t, u, p, now) => { const au = user(+p.assignee_id); if (!au || au.branch_id !== t.branch_id || au.status !== 'active') bad('Pick an active user of your branch'); t.branch_assignee_id = au.id; log(t, 'branch_assigned_staff', u, { from: [t.status, t.level], meta: { assignee: au.id } }, now); notify([au.id], `${t.number} assigned to you`, t, 'assignment'); t.version++ })
def('verify', (t, u) => chk(!isBranch(u) && (isAdmin(u) || lvlOf(u) === 2) && t.status === S.AT, 'Nothing to verify'),
  (t, u, p, now) => {
    if (p.approve) return doResolve(t, u, p.action_taken || 'Branch action verified', p.outcome || text(p.note, 'Outcome', 3), null, false, now, 'verified_resolved')
    const n = text(p.note, 'Reason for rejecting', 5); transition(t, u, 'verification_rejected', S.AB, now, { note: n }); toBranch(t.branch_id, `${t.number}: Head Office needs more action - ${n.slice(0, 120)}`, t, 'assignment')
  })
def('resolve', (t, u) => { chk(!isBranch(u), 'Branch users cannot resolve; mark Action Taken instead'); chk([...Object.values(QUEUE), ...Object.values(WORKING), S.AB, S.BA].includes(t.status), 'Cannot be resolved from this status'); chk(atLevel(u, t), 'Only the owning level can resolve'); if (Object.values(WORKING).includes(t.status)) chk(!t.owner_id || t.owner_id === u.id || isAdmin(u) || (u.is_team_lead && lvlOf(u) === t.level), 'This complaint is being worked by someone else') },
  (t, u, p, now) => { A.resolve.pre(t, u); doResolve(t, u, p.action_taken, p.outcome, p.root_cause, !!p.first_call, now) })
function doResolve(t, u, action, outcome, root, first, now, type = 'resolved') {
  action = text(action, 'Action taken', 3); outcome = text(outcome, 'Outcome', 3); const l = t.level
  transition(t, u, type, S.RES, now, { note: outcome, meta: { first_call: first } }); t.resolved_at = now; t.resolved_level = l; t.resolution = { action, outcome, root_cause: root, first_call: first, resolved_at: now }
  toCustomer(t, `Your complaint ${t.number} has been resolved.`); toBranch(t.branch_id, `${t.number} resolved`, t)
}
def('close', (t, u) => { chk(t.status === S.RES, 'Only a resolved complaint can be closed'); chk(!isBranch(u) && (isAdmin(u) || lvlOf(u) === 3 || (lvlOf(u) === 2 && t.priority !== 'critical')), 'You cannot close this complaint') },
  (t, u, p, now) => { transition(t, u, 'closed', S.CL, now, { rearm: false }); t.closed_at = now; t.due_at = null })
def('reopen', (t, u) => { chk([S.RES, S.CL].includes(t.status), 'Only resolved or closed complaints can be reopened'); chk(!isBranch(u) && (isAdmin(u) || [2, 3].includes(lvlOf(u))), 'Only L2, L3 or Admin can reopen') },
  (t, u, p, now) => reopen(t, u, p.reason, now, false))
function reopen(t, u, reason, now, system) {
  reason = text(reason, 'Reason', 3); const ref = t.closed_at || t.resolved_at
  if ((system || !isAdmin(u)) && ref && now - ref > DB.rules.reopen_window_days * 86400000) bad('The reopen window has passed')
  const l = t.resolved_level || 2; transition(t, system ? null : u, 'reopened', QUEUE[l], now, { owner: null, reason, trigger: system ? 'system' : 'manual', actor_type: system ? 'customer' : undefined })
  t.reopen_count++; t.closed_at = null; t.cooling = false; toLevel(l, `${t.number} reopened: ${reason}`, t, 'reopen')
}
function pause(t, u, to, now, reason) {
  t.remaining_minutes = t.due_at ? workingBetween(now, t.due_at) : null; t.paused_from = t.status
  transition(t, u, 'paused', to, now, { reason, rearm: to === S.ABI, meta: { kind: to } }); if (to === S.AC) t.due_at = null
}
def('await_customer', (t, u) => { chk(!isBranch(u) && atLevel(u, t), 'Only the owning level can pause for the customer'); chk([...Object.values(QUEUE), ...Object.values(WORKING), S.AB, S.BA].includes(t.status), 'Cannot pause in this status') },
  (t, u, p, now) => pause(t, u, S.AC, now, text(p.reason, 'Reason', 3)))
def('return_for_info', (t, u) => { chk(!isBranch(u) && (isAdmin(u) || lvlOf(u) === 1) && t.level === 1, 'Only L1 can ask the branch'); chk(t.origin_branch_id != null, 'This complaint was not registered by a branch'); chk([S.L1Q, S.L1W].includes(t.status), 'Complaint is not at L1') },
  (t, u, p, now) => { const q = text(p.question, 'Question', 5); pause(t, u, S.ABI, now, q); t.messages.push({ id: nid('m'), channel: 'thread', author_id: u.id, body: q, at: now }); toBranch(t.origin_branch_id, `${t.number}: Head Office needs information - ${q.slice(0, 100)}`, t, 'info_request') })
def('resume', (t, u) => { chk(PAUSED.includes(t.status), 'Complaint is not paused'); chk((!isBranch(u) && (isAdmin(u) || lvlOf(u) === t.level)) || (t.status === S.ABI && isBranch(u) && u.branch_id === t.origin_branch_id), 'Not allowed to resume') },
  (t, u, p, now) => resume(t, u, now, false))
function resume(t, u, now, system) {
  const back = t.paused_from || QUEUE[t.level || 1], rem = t.remaining_minutes
  transition(t, system ? null : u, 'resumed', back, now, { rearm: false, trigger: system ? 'system' : 'manual', actor_type: system ? 'customer' : undefined }); arm(t, now, rem > 0 ? rem : undefined); t.paused_from = null; t.remaining_minutes = null
}
def('forward', (t, u) => chk(t.status === S.DRAFT && isBranch(u) && u.branch_id === t.origin_branch_id, 'Nothing to forward'),
  (t, u, p, now) => { transition(t, u, 'forwarded', S.L1Q, now, { level: 1, note: 'Forwarded to Head Office' }); t.forwarded_at = now; toCustomer(t, `We have registered your complaint ${t.number}.`); if (t.urgent) { toLevel(1, `URGENT: ${t.number} forwarded by a branch`, t, 'alert', true); toLevel(2, `URGENT: ${t.number} forwarded by a branch`, t, 'alert', true) } })
def('withdraw', (t, u) => chk(t.status === S.L1Q && !t.owner_id && isBranch(u) && u.branch_id === t.origin_branch_id && t.forwarded_at, 'It can only be withdrawn before L1 picks it up'),
  (t, u, p, now) => { transition(t, u, 'withdrawn', S.DRAFT, now, { rearm: false }); t.due_at = null; t.forwarded_at = null })
def('set_priority', (t, u) => chk(isHO(u) && OPEN.includes(t.status), 'Not allowed'),
  (t, u, p, now) => { if (!PRI.includes(p.priority)) bad('invalid priority'); const o = t.priority; t.priority = p.priority; if (LEVEL_OF[t.status] && ![S.AB, S.BA].includes(t.status)) arm(t, now); log(t, 'priority_changed', u, { from: [t.status, t.level], meta: { from: o, to: p.priority } }, now); t.version++ })
def('merge', (t, u) => chk(isHO(u) && (OPEN.includes(t.status) || t.status === S.RES), 'Not allowed'),
  (t, u, p, now) => { const tg = tkt(p.into_id); if (!tg || tg.id === t.id || [S.CL, S.DRAFT].includes(tg.status)) bad('Invalid merge target'); transition(t, u, 'merged', S.CL, now, { via: 'merge', rearm: false, meta: { into: tg.number } }); t.merged_into_id = tg.id; t.closed_at = now; t.due_at = null; log(tg, 'merge_received', u, { from: [tg.status, tg.level], note: `Merged from ${t.number}` }, now); tg.version++ })
const DETAIL = ['consignment_no', 'receiver_name', 'receiver_mobile', 'address', 'pincode', 'preferred_contact', 'preferred_language', 'caller_number', 'call_reference', 'subject', 'category_id']
def('update_details', (t, u) => chk((isHO(u) && !isBranch(u) && atLevel(u, t) && OPEN.includes(t.status)) || (isBranch(u) && t.status === S.DRAFT && u.branch_id === t.origin_branch_id), 'Not allowed to edit details'),
  (t, u, p, now) => { const ch = {}; for (const [k, v0] of Object.entries(p)) { if (!DETAIL.includes(k)) bad(`${k} cannot be edited (the original description is immutable)`); const v = ['receiver_mobile', 'caller_number'].includes(k) ? normMobile(v0) : v0; if ((t[k] || null) !== (v || null)) { ch[k] = { from: t[k], to: v }; t[k] = v || null } }
    if (!Object.keys(ch).length) bad('No changes to save'); t.incomplete = incomplete(t); log(t, 'details_updated', u, { from: [t.status, t.level], meta: ch }, now); touch(t, u, now); t.version++ })
def('admin_force', (t, u) => chk(isAdmin(u), 'Admin only'),
  (t, u, p, now) => { const r = text(p.reason, 'Reason', 5); if (!ALL.includes(p.to_status)) bad('unknown status'); transition(t, u, 'admin_force', p.to_status, now, { via: 'admin_force', trigger: 'admin_force', reason: r, owner: Object.values(QUEUE).includes(p.to_status) ? null : KEEP, rearm: ![S.CL, S.DRAFT].includes(p.to_status) }); if (p.to_status === S.CL) { t.closed_at = now; t.due_at = null } })

const available = (t, u) => Object.keys(A).filter(n => { try { A[n].pre(t, u); return true } catch { return false } })
function runAction(t, u, name, params, expected) {
  if (!A[name]) bad('unknown action ' + name)
  if (expected != null && t.version !== expected) throw new Err('This complaint was changed by someone else. Reload and try again.', 409)
  A[name].pre(t, u); const snap = JSON.stringify(DB)
  try { A[name].run(t, u, params || {}, T()) } catch (e) { DB = JSON.parse(snap); throw e }   // roll back partial changes on error
}

function postMessage(t, u, channel, body, now = T()) {
  body = text(body, 'Message')
  if (channel === 'thread') chk(isHO(u) || (isBranch(u) && branchCanWrite(u, t) && t.status !== S.DRAFT), 'Cannot post to this thread')
  else if (channel === 'note') chk(isHO(u) && !isBranch(u), 'Notes are for Head Office only')
  else if (channel === 'customer_out') { chk(isHO(u) && !isBranch(u), 'Only Head Office can message the customer'); toCustomer(t, body) }
  else bad('unknown channel')
  t.messages.push({ id: nid('m'), channel, author_id: u.id, body, at: now })
  if (channel === 'thread') {
    if (isBranch(u)) { t.owner_id ? notify([t.owner_id], `${t.number}: new message from branch`, t, 'message') : toLevel(t.level || 1, `${t.number}: new message from branch`, t, 'message') } else toBranch(t.branch_id || t.origin_branch_id, `${t.number}: message from Head Office`, t, 'message')
    if (isBranch(u) && t.status === S.ABI && u.branch_id === t.origin_branch_id) resume(t, u, now, false)
  }
  touch(t, u, now); log(t, 'message', u, { from: [t.status, t.level], meta: { channel } }, now); t.version++
}

// ------------------------------------------------------------------ SLA scanner
function autoEscalate(t, now, trigger) {
  const f = t.level; transition(t, null, 'escalated', QUEUE[f + 1], now, { owner: null, trigger, reason: trigger === 'auto_sla' ? `Unattended beyond the L${f} threshold` : 'Branch deadline missed', meta: { rule: trigger } })
  t.escalation_count++; t.cooling = false; const msg = `${t.number} auto-escalated to L${f + 1} (unattended)`; toLevel(f + 1, msg, t, 'escalation'); toLevel(f, msg, t, 'escalation', true); notify([t.owner_id], msg, t, 'escalation'); t.owner_id = null
}
export function scan(now = T()) {
  const r = DB.rules; let n = 0
  for (const t of DB.tickets) {
    if (!t.due_at || t.due_at > now) continue
    const s = t.status
    if ([S.L1Q, S.L1W, S.L2Q, S.L2W, S.AT].includes(s)) { autoEscalate(t, now, 'auto_sla'); n++ }
    else if ([S.AB, S.BA].includes(s)) { if (r.branch_breach_action === 'escalate_l3') autoEscalate(t, now, 'branch_breach'); else { log(t, 'branch_deadline_missed', null, { from: [s, t.level], trigger: 'branch_breach' }, now); toLevel(2, `${t.number}: branch deadline missed`, t, 'alert', true); arm(t, now) } n++ }
    else if ([S.L3Q, S.L3W].includes(s)) { log(t, 'l3_breach_alert', null, { from: [s, t.level], trigger: 'auto_sla' }, now); toAdmins(`${t.number}: L3 threshold breached and no higher level exists`, t); toLevel(3, `${t.number}: L3 threshold breached`, t, 'alert', true); t.due_at = now + r.l3_repeat_minutes * MIN; t.warned_at = null; n++ }
    else if (s === S.ABI) { log(t, 'branch_info_overdue', null, { from: [s, t.level], trigger: 'auto_sla' }, now); toLevel(2, `${t.number}: branch has not answered the information request`, t, 'alert', true); arm(t, now); n++ }
    else if (s === S.RES) { transition(t, null, 'auto_closed', S.CL, now, { rearm: false, trigger: 'system', note: 'Auto-closed after the confirmation period' }); t.closed_at = now; t.due_at = null; n++ }
  }
  for (const t of DB.tickets) {   // 80% warnings
    if (!t.due_at || t.due_at <= now || t.warned_at || !t.last_activity_at || ![...Object.keys(LEVEL_OF), S.ABI].includes(t.status)) continue
    const total = workingBetween(t.last_activity_at, t.due_at), used = workingBetween(t.last_activity_at, now)
    if (total > 0 && used >= r.warn_pct * total) { const m = `${t.number}: ${Math.round(r.warn_pct * 100)}% of the time limit used`; notify([t.owner_id, t.branch_assignee_id], m, t, 'warning'); [S.AB, S.BA].includes(t.status) ? toBranch(t.branch_id, m, t, 'warning', true) : toLevel(t.level || 1, m, t, 'warning', true); t.warned_at = now }
  }
  save(); return n
}

// ------------------------------------------------------------------ serializers
const userOut = u => ({ id: u.id, name: u.name, email: u.email, mobile: u.mobile, role: u.role, branch_id: u.branch_id, branch: u.branch_id ? branchOf(u.branch_id)?.name : null, status: u.status, is_team_lead: !!u.is_team_lead, last_login: iso(u.last_login) })
function ticketOut(t, u, detail) {
  const now = T(), c = DB.customers.find(x => x.id === t.customer_id), cat = DB.categories.find(x => x.id === t.category_id), own = user(t.owner_id)
  const d = { id: t.id, number: t.number, source: t.source, status: t.status, level: t.level, priority: t.priority, urgent: t.urgent, subject: t.subject, incomplete: t.incomplete,
    customer: c ? { id: c.id, name: c.name, mobile: c.mobile, email: c.email } : null, category: cat?.name || null, category_id: t.category_id, owner: own?.name || null, owner_id: t.owner_id,
    branch: t.branch_id ? branchOf(t.branch_id)?.name : null, branch_id: t.branch_id, origin_branch: t.origin_branch_id ? branchOf(t.origin_branch_id)?.name : null, origin_branch_id: t.origin_branch_id,
    consignment_no: t.consignment_no, pincode: t.pincode, created_at: iso(t.created_at), due_at: iso(t.due_at), overdue: !!(t.due_at && t.due_at < now && OPEN.includes(t.status)),
    age_hours: Math.round((now - t.created_at) / 360000) / 10, cooling: t.cooling, repeated_movement: t.repeated_movement, version: t.version, actions: available(t, u) }
  if (t.due_at && (OPEN.includes(t.status) || t.status === S.RES)) d.minutes_left = Math.floor((t.due_at - now) / MIN)
  if (detail) {
    const branchy = isBranch(u)
    Object.assign(d, { description: t.description, receiver_name: t.receiver_name, receiver_mobile: t.receiver_mobile, address: t.address, preferred_contact: t.preferred_contact, preferred_language: t.preferred_language,
      caller_number: t.caller_number, call_received_at: iso(t.call_received_at), call_reference: t.call_reference, branch_deadline_minutes: t.branch_deadline_minutes, extension_count: t.extension_count,
      escalation_count: t.escalation_count, deescalation_count: t.deescalation_count, reopen_count: t.reopen_count, branch_assignee_id: t.branch_assignee_id,
      resolution: t.resolution ? { ...t.resolution, resolved_at: iso(t.resolution.resolved_at) } : null, forwarded_at: iso(t.forwarded_at), merged_into_id: t.merged_into_id })
    d.events = t.events.map(e => ({ id: e.id, at: iso(e.at), type: e.type, actor: user(e.actor_id)?.name || e.actor_type, from_status: e.from_status, to_status: e.to_status, from_level: e.from_level, to_level: e.to_level, trigger: e.trigger, reason_code: e.reason_code, reason: e.reason, note: e.note, meta: branchy ? null : e.meta }))
    d.messages = t.messages.filter(m => !branchy || m.channel === 'thread').map(m => { const a = user(m.author_id); return { id: m.id, channel: m.channel, author: a?.name || m.author_type || 'customer', author_role: a?.role || null, author_type: m.author_type || 'user', body: m.body, at: iso(m.at), read: true } })
    d.attachments = t.attachments
  }
  return d
}

// ------------------------------------------------------------------ dashboard
function dashboard(u) {
  const now = T(), ts = DB.tickets.filter(t => canSee(u, t)), open = ts.filter(t => OPEN.includes(t.status)), cnt = (arr, f) => arr.reduce((a, x) => { const k = f(x); if (k != null) a[k] = (a[k] || 0) + 1; return a }, {})
  const ageing = { '<1 day': 0, '1-3 days': 0, '3-7 days': 0, '>7 days': 0 }; open.forEach(t => { const d = (now - t.created_at) / 86400000; ageing[d < 1 ? '<1 day' : d < 3 ? '1-3 days' : d < 7 ? '3-7 days' : '>7 days']++ })
  const hrs = ts.filter(t => t.resolved_at).map(t => (t.resolved_at - t.created_at) / 3600000).sort((a, b) => a - b), pc = p => hrs.length ? Math.round(hrs[Math.min(hrs.length - 1, Math.floor(hrs.length * p))] * 10) / 10 : null
  const evs = ts.flatMap(t => t.events), out = { total: ts.length, open: open.length, by_status: cnt(ts, t => t.status), open_by_level: Object.fromEntries(Object.entries(cnt(open, t => t.level)).map(([k, v]) => ['L' + k, v])),
    unassigned: open.filter(t => !t.owner_id && Object.values(QUEUE).includes(t.status)).length, overdue: open.filter(t => t.due_at && t.due_at < now).length, ageing, by_source: cnt(ts, t => t.source),
    mine: open.filter(t => t.owner_id === u.id || t.branch_assignee_id === u.id).length, resolution_hours: { median: pc(0.5), p90: pc(0.9), count: hrs.length }, first_call_resolution: ts.filter(t => t.resolution?.first_call).length,
    escalations: { automatic: evs.filter(e => e.type === 'escalated' && ['auto_sla', 'branch_breach'].includes(e.trigger)).length, manual: evs.filter(e => e.type === 'escalated' && ['manual', 'l2_direct'].includes(e.trigger)).length },
    deescalations_by_reason: cnt(evs.filter(e => e.type === 'deescalated'), e => e.reason_code), repeated_movement: open.filter(t => t.repeated_movement).length, reopened: ts.filter(t => t.reopen_count > 0).length }
  if (!isBranch(u)) { const lg = {}; for (const t of ts) for (const b of new Set([t.branch_id, t.origin_branch_id].filter(Boolean))) { const r = lg[b] || (lg[b] = { branch: branchOf(b)?.name, open: 0, resolved: 0, h: [] }); if (OPEN.includes(t.status)) r.open++; if (t.resolved_at && t.branch_id === b) { r.resolved++; r.h.push((t.resolved_at - t.created_at) / 3600000) } }
    out.branch_league = Object.values(lg).map(r => ({ branch: r.branch, open: r.open, resolved: r.resolved, avg_resolution_hours: r.h.length ? Math.round(r.h.reduce((a, b) => a + b, 0) / r.h.length * 10) / 10 : null })).sort((a, b) => b.open - a.open) }
  return out
}
export const exportCsv = () => { load(); const u = cur(); const rows = [['number', 'created_utc', 'source', 'status', 'level', 'priority', 'customer', 'mobile', 'branch', 'owner', 'due_utc']]; DB.tickets.filter(t => canSee(u, t)).forEach(t => { const c = DB.customers.find(x => x.id === t.customer_id); rows.push([t.number, iso(t.created_at), t.source, t.status, t.level, t.priority, c?.name || '', c?.mobile || '', branchOf(t.branch_id)?.name || '', user(t.owner_id)?.name || '', iso(t.due_at) || '']) }); return rows.map(r => r.map(x => `"${String(x ?? '').replace(/"/g, '""')}"`).join(',')).join('\n') }

// ------------------------------------------------------------------ seed
function seed() {
  const day = 86400000, base = Date.now()
  DB = { v: 2, offset: 0, ids: {}, notifications: [], outbox: [], helpdesk: [], invites: [], customers: [], tickets: [], audit: [],
    rules: { default_minutes: 360, critical_minutes: 120, warn_pct: 0.8, branch_deadline_default: 360, branch_deadline_min: 120, branch_deadline_max: 2880, max_extensions: 2, info_limit_minutes: 360, l3_repeat_minutes: 360, branch_breach_action: 'escalate_l3', max_deescalations: 2, repeated_movement_at: 4, auto_close_hours: 48, reopen_window_days: 7, staff_approval: 'branch_admin', invite_hours: 72, min_handover_chars: 20 },
    calendar: { mode: 'business', tz: 'Asia/Kolkata', start: '09:00', end: '19:00', days: [0, 1, 2, 3, 4, 5], holidays: [] }, policies: {},
    regions: [{ id: 1, name: 'West' }, { id: 2, name: 'East' }, { id: 3, name: 'North' }, { id: 4, name: 'South' }],
    categories: [['Delivery delay', 'medium'], ['Not delivered / lost', 'high'], ['Damaged consignment', 'high'], ['Wrong delivery', 'medium'], ['Billing / payment', 'low'], ['Staff behaviour', 'medium'], ['Other', 'low']].map(([name, p], i) => ({ id: i + 1, name, default_priority: p })),
    branches: [], users: [] }
  const br = (id, code, name, city, state, region_id, status, pins) => DB.branches.push({ id, code, name, city, state, address: '', region_id, status, pincodes: pins, contact_name: null, contact_email: null, contact_phone: null })
  br(1, 'MUM01', 'Mumbai Andheri', 'Mumbai', 'Maharashtra', 1, 'live', ['400053', '400058']); br(2, 'KOL01', 'Kolkata Salt Lake', 'Kolkata', 'West Bengal', 2, 'live', ['700091'])
  br(3, 'DEL01', 'Delhi Connaught Place', 'Delhi', 'Delhi', 3, 'live', ['110001']); br(4, 'BLR01', 'Bengaluru Indiranagar', 'Bengaluru', 'Karnataka', 4, 'pending', ['560038'])
  const us = [['Admin', 'SUPER_ADMIN'], ['Priya Sharma', 'L1', null, 1], ['Rahul Verma', 'L1'], ['Neha Kapoor', 'L2', null, 1], ['Arjun Mehta', 'L2'], ['Vikram Rao', 'L3', null, 1],
    ['Anil Patil', 'BRANCH_ADMIN', 1], ['Sunita Joshi', 'BRANCH_STAFF', 1], ['Debu Sen', 'BRANCH_ADMIN', 2], ['Mita Das', 'BRANCH_STAFF', 2], ['Ravi Khanna', 'BRANCH_ADMIN', 3], ['West Regional Manager', 'REGIONAL_MANAGER', null, 0, 1]]
  us.forEach(([name, role, branch_id, lead, region_id], i) => DB.users.push({ id: i + 1, name, email: name.toLowerCase().replace(/ /g, '.') + '@skyking.demo', mobile: null, role, branch_id: branch_id || null, region_id: region_id || null, status: 'active', is_team_lead: !!lead, password: PW, last_login: null }))
  DB.ids = { n: 0, e: 0, m: 0, c: 0, t: 0, num: 0 }
  const U = n => DB.users.find(u => u.name.startsWith(n)), [p, rahul, neha, arjun, vik, anil, sunita, debu, mita] = ['Priya', 'Rahul', 'Neha', 'Arjun', 'Vikram', 'Anil', 'Sunita', 'Debu', 'Mita'].map(U)
  const mk = (who, d, ago) => createTicket(who, d, base - ago * MIN)
  const ph = { source: 'phone_inbound', pincode: '400053' }
  const t1 = mk(p, { ...ph, description: 'Parcel not delivered for 5 days, customer is travelling next week', mobile: '9830011111', name: 'Ritu Agarwal', category_id: 2, consignment_no: 'SKY10021', receiver_name: 'Ritu Agarwal', caller_number: '9830011111', call_reference: 'REC-4411' }, 55)
  mk(null, { source: 'whatsapp', description: 'My package has been showing out for delivery since yesterday', mobile: '9830022222', name: 'Alnizam Jewellers', category_id: 1 }, 240)
  const t3 = mk(p, { ...ph, source: 'email', description: 'Invoice amount differs from the quote we were given', mobile: '9830033333', name: 'Sandeep Traders', category_id: 5, consignment_no: 'SKY10033' }, 200); A.pick.run(t3, rahul, {}, base - 190 * MIN)
  const t4 = mk(p, { ...ph, description: 'Box arrived crushed, contents damaged', mobile: '9830044444', name: 'Kavita Rao', category_id: 3, consignment_no: 'SKY10044' }, 300); A.pick.run(t4, p, {}, base - 290 * MIN); A.escalate.run(t4, p, { reason: 'Needs branch investigation' }, base - 280 * MIN); A.pick.run(t4, neha, {}, base - 270 * MIN)
  const t5 = mk(p, { ...ph, description: 'Wrong person signed for the parcel', mobile: '9830055555', name: 'Manish Gupta', category_id: 4, consignment_no: 'SKY10055' }, 420); A.pick.run(t5, p, {}, base - 410 * MIN); A.escalate.run(t5, p, { reason: 'Delivery dispute' }, base - 400 * MIN); A.pick.run(t5, neha, {}, base - 390 * MIN); A.assign_branch.run(t5, neha, { branch_id: 1, deadline_minutes: 240 }, base - 380 * MIN)
  const t6 = mk(p, { ...ph, pincode: '700091', description: 'Consignment stuck at Kolkata hub for 3 days', mobile: '9830066666', name: 'Soma Banerjee', category_id: 1, consignment_no: 'SKY10066' }, 500); A.pick.run(t6, p, {}, base - 490 * MIN); A.escalate.run(t6, p, { reason: 'Hub issue' }, base - 480 * MIN); A.pick.run(t6, arjun, {}, base - 470 * MIN); A.assign_branch.run(t6, arjun, { branch_id: 2, deadline_minutes: 480 }, base - 460 * MIN); A.branch_ack.run(t6, mita, {}, base - 440 * MIN)
  const t7 = mk(p, { ...ph, description: 'High-value electronics lost in transit, customer escalating to legal', mobile: '9830077777', name: 'Techno Mart', category_id: 2, consignment_no: 'SKY10077', priority: 'critical' }, 600); A.pick.run(t7, p, {}, base - 590 * MIN); A.escalate.run(t7, p, { reason: 'Critical, legal threat' }, base - 580 * MIN); A.pick.run(t7, neha, {}, base - 570 * MIN); A.escalate.run(t7, neha, { reason: 'Needs senior decision' }, base - 560 * MIN); A.pick.run(t7, vik, {}, base - 550 * MIN)
  mk(sunita, { description: 'Customer walked in: parcel delivered with broken seal', mobile: '9820088888', name: 'Asha Naik', category_id: 3, consignment_no: 'SKY10088', pincode: '400058', urgent: true }, 25)
  mk(p, { ...ph, description: 'Wrong delivery address, resolved by redelivery', mobile: '9830099999', name: 'Farhan Ali', category_id: 4, consignment_no: 'SKY10099', mode: 'take', resolve: { action_taken: 'Redelivered to correct address', outcome: 'Customer satisfied' } }, 1500)
  const t10 = mk(p, { ...ph, description: 'Courier staff rude to elderly customer', mobile: '9830012121', name: 'Mrs. Iyer', category_id: 6, consignment_no: 'SKY10121' }, 900); A.pick.run(t10, p, {}, base - 890 * MIN); A.escalate.run(t10, p, { reason: 'Staff conduct' }, base - 880 * MIN); A.pick.run(t10, neha, {}, base - 870 * MIN); A.escalate.run(t10, neha, { reason: 'Conduct case' }, base - 860 * MIN); A.pick.run(t10, vik, {}, base - 850 * MIN)
  A.deescalate.run(t10, vik, { reason_code: 'escalated_too_early', note: 'Please get the branch manager statement before this comes back to L3.' }, base - 120 * MIN)
  mk(sunita, { description: 'Customer phoned the branch about a missing parcel (draft)', mobile: '9820013131', category_id: 2, mode: 'draft' }, 10)
  const t12 = mk(p, { ...ph, description: 'Delay in delivery, now delivered', mobile: '9830014141', name: 'Joy Dutta', category_id: 1, consignment_no: 'SKY10141', mode: 'take', resolve: { action_taken: 'Delivered', outcome: 'Confirmed by customer' } }, 3000); A.close.run(t12, neha, {}, base - 2900 * MIN)
  DB.notifications.forEach(n => { n.read = n.at < base - 60 * MIN })
  return DB
}

// ------------------------------------------------------------------ session + router
const cur = () => { const id = +store.getItem(SESS); const u = id && user(id); if (!u || u.status !== 'active') throw new Err('Not authenticated', 401); return u }
export function load() { if (DB) return DB; try { const s = store.getItem(KEY); if (s) { DB = JSON.parse(s); if (DB.v === 2) return DB } } catch {} seed(); save(); return DB }
export function resetDemo() { DB = null; store.removeItem(KEY); store.removeItem(SESS) }
export function advance(minutes, working = false) { load(); DB.offset = (DB.offset || 0) + (working ? addWorking(T(), minutes) - T() : minutes * MIN); scan(); save() }
export const demoClock = () => { load(); return T() }
export const demoSession = () => { try { load(); return userOut(cur()) } catch { return null } }
export const demoAccounts = () => { load(); return DB.users.filter(u => u.status === 'active').map(u => ({ email: u.email, name: u.name, role: u.role, branch: u.branch_id ? branchOf(u.branch_id)?.name : null })) }
export function demoLogout() { store.removeItem(SESS) }
const clone = x => (x === undefined ? {} : JSON.parse(JSON.stringify(x)))

export async function demoApi(path, opts = {}) {
  load(); scan()
  const method = (opts.method || 'GET').toUpperCase(), [p, qs] = path.split('?'), q = Object.fromEntries(new URLSearchParams(qs || '')), b = opts.body && !(opts.body instanceof FormData) ? opts.body : {}
  const m = re => { const r = p.match(re); return r }; let r
  const done = v => { save(); return clone(v) }
  // ---- auth
  if (p === '/auth/login') { const id = (b.username || '').trim().toLowerCase(), u = DB.users.find(x => x.email === id || (x.mobile && x.mobile === normMobile(id))); if (!u || u.status !== 'active' || u.password !== b.password) throw new Err('Incorrect username or password', 401); u.last_login = T(); store.setItem(SESS, u.id); return done({ access_token: 'demo', refresh_token: 'demo', user: userOut(u) }) }
  if (p === '/auth/invite-info') { const i = DB.invites.find(x => x.token === q.token && ['pending', 'awaiting_approval'].includes(x.status)); if (!i) throw new Err('Invitation is invalid or has expired', 404); return clone({ name: i.name, role: i.role, branch: i.branch_id ? branchOf(i.branch_id)?.name : null, purpose: 'invite', awaiting_approval: i.status === 'awaiting_approval' }) }
  if (p === '/auth/accept-invite') { const i = DB.invites.find(x => x.token === b.token && ['pending', 'awaiting_approval'].includes(x.status)); if (!i) bad('This invitation is invalid or has expired'); if (i.status === 'awaiting_approval') bad('This invitation is waiting for Head Office approval'); if ((b.password || '').length < 10 || !/\d/.test(b.password) || !/[A-Za-z]/.test(b.password)) bad('Password must be at least 10 characters with letters and digits'); if (i.purpose === 'reset') user(i.user_id).password = b.password; else DB.users.push({ id: DB.users.reduce((a, x) => Math.max(a, x.id), 0) + 1, name: i.name, email: i.email, mobile: i.mobile, role: i.role, branch_id: i.branch_id, region_id: null, status: 'active', is_team_lead: false, password: b.password, last_login: null }); i.status = 'accepted'; return done({ ok: true, email: i.email, mobile: i.mobile }) }
  const u = cur()
  if (p === '/auth/me') return clone(userOut(u))
  // ---- tickets
  if (p === '/tickets' && method === 'GET') {
    let rows = DB.tickets.filter(t => canSee(u, t)); const ql = (q.q || '').toLowerCase()
    if (ql) rows = rows.filter(t => { const c = DB.customers.find(x => x.id === t.customer_id); return [t.number, t.subject, t.consignment_no, c?.mobile, c?.name, c?.email].some(v => (v || '').toLowerCase().includes(ql)) })
    if (q.status) rows = rows.filter(t => t.status === q.status); if (q.level) rows = rows.filter(t => t.level === +q.level); if (q.priority) rows = rows.filter(t => t.priority === q.priority); if (q.source) rows = rows.filter(t => t.source === q.source)
    if (q.open_only === 'true') rows = rows.filter(t => OPEN.includes(t.status)); if (q.overdue === 'true') rows = rows.filter(t => t.due_at && t.due_at < T() && OPEN.includes(t.status))
    if (q.mine === 'true') rows = rows.filter(t => t.owner_id === u.id || t.branch_assignee_id === u.id)
    if (q.queue === 'true') rows = rows.filter(t => !t.owner_id && Object.values(QUEUE).includes(t.status) && (!lvlOf(u) || t.level === lvlOf(u)))
    rows.sort((a, b) => (a.due_at ?? Infinity) - (b.due_at ?? Infinity) || b.id - a.id); const page = +q.page || 1
    return clone({ total: rows.length, page, items: rows.slice((page - 1) * 25, page * 25).map(t => ticketOut(t, u)) })
  }
  if (p === '/tickets' && method === 'POST') { const t = createTicket(u, b); return done(ticketOut(t, u, true)) }
  if (p === '/tickets/check-duplicate') { const c = findCustomer(b.mobile, b.email); if (!c) return clone({ customer: null, open_complaints: [], duplicates: [] }); const open = DB.tickets.filter(t => canSee(u, t) && t.customer_id === c.id && OPEN.includes(t.status)), br = t => ({ id: t.id, number: t.number, status: t.status, subject: t.subject, consignment_no: t.consignment_no }); return clone({ customer: c, open_complaints: open.map(br), duplicates: open.filter(t => b.consignment_no && t.consignment_no === b.consignment_no).map(br) }) }
  if (p === '/tickets/suggest-branch') { chk(!isBranch(u)); return clone(DB.branches.filter(x => x.status === 'live' && x.pincodes.includes((q.pincode || '').trim())).map(x => ({ id: x.id, code: x.code, name: x.name, city: x.city }))) }
  if ((r = m(/^\/tickets\/(\d+)$/)) && method === 'GET') { const t = tkt(r[1]); if (!t || !canSee(u, t)) throw new Err('Complaint not found', 404); return clone(ticketOut(t, u, true)) }
  if ((r = m(/^\/tickets\/(\d+)\/actions$/))) { const t = tkt(r[1]); if (!t || !canSee(u, t)) throw new Err('Complaint not found', 404); runAction(t, u, b.action, b.params, b.version); return done(ticketOut(tkt(r[1]), u, true)) }
  if ((r = m(/^\/tickets\/(\d+)\/messages$/))) { const t = tkt(r[1]); if (!t || !canSee(u, t)) throw new Err('Complaint not found', 404); postMessage(t, u, b.channel, b.body); return done(ticketOut(t, u, true)) }
  if ((r = m(/^\/tickets\/(\d+)\/attachments$/))) { const t = tkt(r[1]); if (!t || !canSee(u, t)) throw new Err('Complaint not found', 404); const f = opts.body.get('file'); t.attachments.push({ id: nid('a'), filename: f.name, size: f.size, content_type: f.type }); log(t, 'attachment_added', u, { from: [t.status, t.level], meta: { filename: f.name } }); return done({ ok: true }) }
  // ---- helpdesk
  if (p === '/helpdesk' && method === 'GET') { const bid = isBranch(u) ? u.branch_id : +q.branch_id; return clone(DB.helpdesk.filter(x => x.branch_id === bid).map(x => ({ id: x.id, author: user(x.author_id)?.name, author_role: user(x.author_id)?.role, body: x.body, at: iso(x.at) }))) }
  if (p === '/helpdesk' && method === 'POST') { const bid = isBranch(u) ? u.branch_id : +b.branch_id; if (!bid) bad('branch_id is required'); DB.helpdesk.push({ id: nid('h'), branch_id: bid, author_id: u.id, body: text(b.body, 'Message'), at: T() }); isBranch(u) ? toLevel(1, `Help desk message from ${branchOf(bid).name}`, null, 'helpdesk', true) : toBranch(bid, 'Message from Head Office help desk', null, 'helpdesk'); return done({ ok: true }) }
  // ---- branches / regions
  if (p === '/regions') return method === 'POST' ? (chk(isAdmin(u)), DB.regions.push({ id: nid('r') + 10, name: b.name }), done({ ok: true })) : clone(DB.regions)
  if (p === '/branches' && method === 'GET') return clone(DB.branches.filter(x => isBranch(u) ? x.id === u.branch_id : u.role === 'REGIONAL_MANAGER' ? x.region_id === u.region_id : true).map(x => ({ ...x, region: DB.regions.find(g => g.id === x.region_id)?.name || null })))
  if (p === '/branches' && method === 'POST') { chk(isAdmin(u)); const code = (b.code || '').trim().toUpperCase(); if (DB.branches.some(x => x.code === code)) bad('Branch code already exists'); const nb = { id: DB.branches.reduce((a, x) => Math.max(a, x.id), 0) + 1, code, name: b.name, city: b.city, state: b.state, address: b.address, region_id: b.region_id, status: 'pending', pincodes: b.pincodes || [] }; DB.branches.push(nb); return done(nb) }
  if (p === '/branches/import') { chk(isAdmin(u)); const txt = await opts.body.get('file').text(), lines = txt.trim().split(/\r?\n/), hdr = lines.shift().split(',').map(s => s.trim()); let created = 0, updated = 0; const errors = []
    lines.forEach((ln, i) => { const c = ln.split(','), o = Object.fromEntries(hdr.map((h, j) => [h, (c[j] || '').trim()])); if (!o.code || !o.name) return errors.push({ row: i + 2, error: 'code and name are required' }); let ex = DB.branches.find(x => x.code === o.code.toUpperCase()); const reg = o.region ? (DB.regions.find(x => x.name === o.region) || (DB.regions.push({ id: nid('r') + 10, name: o.region }), DB.regions.at(-1))) : null
      if (!ex) { ex = { id: DB.branches.reduce((a, x) => Math.max(a, x.id), 0) + 1, code: o.code.toUpperCase(), name: o.name, status: 'pending', pincodes: [] }; DB.branches.push(ex); created++ } else updated++; ex.name = o.name; ex.city = o.city || ex.city; ex.state = o.state || ex.state; if (reg) ex.region_id = reg.id; (o.pincodes || '').split(';').filter(Boolean).forEach(pc => /^\d{6}$/.test(pc) ? (!ex.pincodes.includes(pc) && ex.pincodes.push(pc)) : errors.push({ row: i + 2, error: 'bad pincode ' + pc })) }); return done({ created, updated, errors }) }
  if ((r = m(/^\/branches\/(\d+)$/)) && method === 'PATCH') { chk(isAdmin(u)); const x = branchOf(+r[1]); let released = 0
    if (b.status) { if (b.status === 'live' && !DB.users.some(y => y.branch_id === x.id && y.role === 'BRANCH_ADMIN' && y.status === 'active')) bad('A branch needs an active Branch Admin before it can go live'); x.status = b.status
      if (b.status === 'suspended') DB.tickets.filter(t => t.branch_id === x.id && BRANCH_PHASE.includes(t.status)).forEach(t => { t.branch_id = null; t.branch_assignee_id = null; transition(t, u, 'branch_suspended', S.L2Q, T(), { owner: null, trigger: 'system', reason: `Branch ${x.code} suspended` }); toLevel(2, `${t.number} returned to L2: branch ${x.code} suspended`, t, 'alert'); released++ }) }
    return done({ ...x, tickets_returned: released }) }
  // ---- users / invitations
  if (p === '/users' && method === 'GET') { chk(isAdmin(u) || u.role === 'BRANCH_ADMIN'); return clone(DB.users.filter(x => isAdmin(u) || x.branch_id === u.branch_id).map(userOut)) }
  if (p === '/users/directory') return clone(DB.users.filter(x => x.status === 'active' && (isBranch(u) ? x.branch_id === u.branch_id : lvlOf(x) && (!q.level || lvlOf(x) === +q.level))).map(x => ({ id: x.id, name: x.name, role: x.role })))
  const invOut = i => ({ id: i.id, name: i.name, role: i.role, email: i.email, mobile: i.mobile, status: i.status, branch: i.branch_id ? branchOf(i.branch_id)?.name : null, branch_id: i.branch_id, purpose: i.purpose })
  if (p === '/invitations' && method === 'GET') { chk(isAdmin(u) || u.role === 'BRANCH_ADMIN'); return clone(DB.invites.filter(i => i.purpose === 'invite' && (isAdmin(u) || i.branch_id === u.branch_id)).reverse().map(invOut)) }
  if (p === '/invitations' && method === 'POST') {
    let role = b.role, bid = b.branch_id; if (!b.email && !b.mobile) bad('Email or mobile is required')
    if (isBranch(u)) { chk(u.role === 'BRANCH_ADMIN', 'Only a Branch Admin can invite staff'); chk(['BRANCH_ADMIN', 'BRANCH_STAFF'].includes(role), 'A branch cannot create Head Office users'); bid = u.branch_id } else { chk(isAdmin(u), 'Not allowed to invite users'); if (role.startsWith('BRANCH') && !bid) bad('Branch is required') }
    const email = (b.email || '').trim().toLowerCase() || null, mobile = normMobile(b.mobile); if (DB.users.some(x => (email && x.email === email) || (mobile && x.mobile === mobile))) bad('A user with this email or mobile already exists')
    const needs = isBranch(u) && (DB.rules.staff_approval === 'all' || (DB.rules.staff_approval === 'branch_admin' && role === 'BRANCH_ADMIN')), tok = Math.random().toString(36).slice(2) + Date.now().toString(36)
    const i = { id: nid('i'), purpose: 'invite', name: b.name, email, mobile, role, branch_id: bid || null, token: tok, status: needs ? 'awaiting_approval' : 'pending' }; DB.invites.push(i); return done({ ...invOut(i), invite_link: '/accept-invite?token=' + tok }) }
  if ((r = m(/^\/invitations\/(\d+)\/(approve|revoke)$/))) { const i = DB.invites.find(x => x.id === +r[1]); if (r[2] === 'approve') { chk(isAdmin(u), 'Head Office approval required'); if (i.status !== 'awaiting_approval') bad('Nothing to approve'); i.status = 'pending' } else { chk(isAdmin(u) || (u.role === 'BRANCH_ADMIN' && i.branch_id === u.branch_id)); if (i.status === 'accepted') bad('Already accepted'); i.status = 'revoked' } return done(invOut(i)) }
  if ((r = m(/^\/users\/(\d+)$/)) && method === 'PATCH') { const x = user(+r[1]); let released = 0
    if (b.status) { chk(isAdmin(u) || (u.role === 'BRANCH_ADMIN' && x.branch_id === u.branch_id && x.id !== u.id)); x.status = b.status
      if (b.status === 'suspended') { DB.tickets.filter(t => t.owner_id === x.id && OPEN.includes(t.status)).forEach(t => { if (Object.values(WORKING).includes(t.status)) transition(t, u, 'owner_released', QUEUE[t.level], T(), { owner: null, trigger: 'system', reason: 'Owner deactivated or on leave' }); else t.owner_id = null; toLevel(t.level || 1, `${t.number} is back in the queue (owner unavailable)`, t, 'alert', true); released++ }); DB.tickets.filter(t => t.branch_assignee_id === x.id && OPEN.includes(t.status)).forEach(t => { t.branch_assignee_id = null; released++ }) } }
    if (b.is_team_lead != null) { chk(isAdmin(u)); x.is_team_lead = b.is_team_lead } return done({ ...userOut(x), tickets_released: released }) }
  if ((r = m(/^\/users\/(\d+)\/reset-password$/))) { chk(isAdmin(u) || u.role === 'BRANCH_ADMIN'); const tok = Math.random().toString(36).slice(2); DB.invites.push({ id: nid('i'), purpose: 'reset', user_id: +r[1], token: tok, status: 'pending' }); return done({ reset_link: '/accept-invite?token=' + tok }) }
  // ---- notifications / categories / settings / reports
  if (p === '/notifications' && method === 'GET') { const mine = DB.notifications.filter(n => n.user_id === u.id).sort((a, b) => b.id - a.id); return clone({ unread: mine.filter(n => !n.read).length, items: mine.slice(0, 50).map(n => ({ ...n, at: iso(n.at) })) }) }
  if (p === '/notifications/read') { DB.notifications.filter(n => n.user_id === u.id).forEach(n => { n.read = true }); return done({ ok: true }) }
  if (p === '/categories') return clone(DB.categories)
  if (p === '/settings') { chk(isAdmin(u)); return clone({ rules: DB.rules, calendar: DB.calendar, policies: [1, 2, 3].flatMap(l => PRI.map(pr => ({ level: l, priority: pr, minutes: threshold(l, pr) }))) }) }
  if (p === '/settings/rules') { chk(isAdmin(u)); for (const k of Object.keys(b)) if (!(k in DB.rules)) bad('unknown settings: ' + k); Object.assign(DB.rules, b); return done(DB.rules) }
  if (p === '/settings/calendar') { chk(isAdmin(u)); Object.assign(DB.calendar, b); return done(DB.calendar) }
  if (p === '/settings/policy') { chk(isAdmin(u)); if (b.minutes < 5) bad('invalid policy'); DB.policies[`${b.level}:${b.priority}`] = +b.minutes; return done({ ok: true }) }
  if (p === '/reports/dashboard') return clone(dashboard(u))
  throw new Err('Not available in the demo: ' + p, 404)
}
