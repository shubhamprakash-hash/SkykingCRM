import { useEffect, useRef, useState } from 'react'

const tz = 'Asia/Kolkata'
export const fmt = iso => iso ? new Date(iso).toLocaleString('en-IN', { timeZone: tz, day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: true }) : '—'

export const STATUS = {
  DRAFT: 'Draft', L1_QUEUE: 'L1 queue', L1_WORKING: 'L1 working', L2_QUEUE: 'L2 queue', L2_WORKING: 'L2 working',
  ASSIGNED_BRANCH: 'Assigned to branch', BRANCH_ACK: 'Branch acknowledged', ACTION_TAKEN: 'Action taken (verify)',
  L3_QUEUE: 'L3 queue', L3_WORKING: 'L3 working', AWAITING_CUSTOMER: 'Awaiting customer',
  AWAITING_BRANCH_INFO: 'Awaiting branch info', RESOLVED: 'Resolved', CLOSED: 'Closed',
}
export const SOURCES = { whatsapp: 'WhatsApp', email: 'Email', phone_inbound: 'Phone call', phone_callback: 'Callback', walk_in: 'Walk-in', branch: 'Branch', other: 'Other' }
export const ROLES = { SUPER_ADMIN: 'Super Admin', HO_ADMIN: 'HO Admin', L1: 'L1', L2: 'L2', L3: 'L3', REGIONAL_MANAGER: 'Regional Manager', BRANCH_ADMIN: 'Branch Admin', BRANCH_STAFF: 'Branch Staff' }

export function Badge({ status }) {
  const cls = status === 'RESOLVED' || status === 'CLOSED' ? 'ok' : status?.startsWith('L3') ? 'hot' : status?.includes('BRANCH') || status === 'ACTION_TAKEN' ? 'branch' : status?.startsWith('AWAITING') ? 'wait' : ''
  return <span className={'badge ' + cls}>{STATUS[status] || status}</span>
}

export function Priority({ p }) { return <span className={'pri ' + p}>{p}</span> }

export function Timer({ t }) {
  if (t.minutes_left === undefined || t.status === 'CLOSED') return <span className="muted">—</span>
  const m = t.minutes_left
  const abs = Math.abs(m), h = Math.floor(abs / 60), mm = abs % 60
  const txt = (h ? h + 'h ' : '') + mm + 'm'
  if (t.status === 'RESOLVED') return <span className="muted">auto-close in {txt}</span>
  return <span className={m < 0 ? 'late' : m < 60 ? 'soon' : 'muted'}>{m < 0 ? 'overdue ' + txt : txt + ' left'}</span>
}

export function useInterval(fn, ms) {
  const ref = useRef(fn); ref.current = fn
  useEffect(() => { const id = setInterval(() => ref.current(), ms); return () => clearInterval(id) }, [ms])
}

export function useLoad(fn, deps = []) {
  const [state, set] = useState({ data: null, error: null, loading: true })
  const run = async () => {
    try { const data = await fn(); set({ data, error: null, loading: false }) }
    catch (e) { set(s => ({ ...s, error: e.message, loading: false })) }
  }
  useEffect(() => { run() }, deps)
  return { ...state, reload: run }
}

export function Msg({ error, ok }) {
  if (error) return <div className="alert err">{error}</div>
  if (ok) return <div className="alert ok">{ok}</div>
  return null
}
