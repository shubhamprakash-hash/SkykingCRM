import { demoApi, demoSession, demoLogout, exportCsv } from './demo/engine'

// Prototype build runs entirely in the browser (no server). Set VITE_DEMO=false to talk to the real backend.
export const DEMO = import.meta.env.VITE_DEMO !== 'false'
export const linkBase = () => location.origin + (DEMO ? '/#' : '')

let access = null
const RT = 'sk_refresh'

export function setSession(d) {
  if (DEMO) return
  access = d.access_token
  localStorage.setItem(RT, d.refresh_token)
}
export function clearSession() { access = null; localStorage.removeItem(RT); if (DEMO) demoLogout() }

function build(path, opts = {}) {
  const headers = { ...(opts.headers || {}) }
  if (access) headers.Authorization = 'Bearer ' + access
  let body = opts.body
  if (body && !(body instanceof FormData)) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(body) }
  return fetch('/api' + path, { ...opts, headers, body })
}

export async function refresh() {
  if (DEMO) return demoSession()
  const t = localStorage.getItem(RT)
  if (!t) return null
  const r = await fetch('/api/auth/refresh', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ refresh_token: t }) })
  if (!r.ok) { clearSession(); return null }
  const d = await r.json(); setSession(d); return d.user
}

export async function api(path, opts) {
  if (DEMO) return demoApi(path, opts)
  let r = await build(path, opts)
  if (r.status === 401 && !path.startsWith('/auth/login') && await refresh()) r = await build(path, opts)
  const isJson = (r.headers.get('content-type') || '').includes('json')
  const data = isJson ? await r.json() : await r.text()
  if (!r.ok) {
    let msg = data?.detail ?? 'Request failed'
    if (Array.isArray(msg)) msg = msg.map(m => m.msg).join('; ')
    const e = new Error(msg); e.status = r.status; e.data = data; throw e
  }
  return data
}

export async function download(path, filename) {
  if (DEMO) {
    if (!path.includes('export.csv')) return alert('Attachments are not stored in the prototype demo.')
    const url = URL.createObjectURL(new Blob([exportCsv()], { type: 'text/csv' }))
    const el = document.createElement('a'); el.href = url; el.download = filename; el.click(); URL.revokeObjectURL(url); return
  }
  const r = await build(path)
  if (!r.ok) throw new Error('Download failed')
  const url = URL.createObjectURL(await r.blob())
  const a = document.createElement('a'); a.href = url; a.download = filename; a.click(); URL.revokeObjectURL(url)
}
