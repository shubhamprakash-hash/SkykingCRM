import { createContext, useContext, useEffect, useState } from 'react'
import { api, setSession, clearSession, refresh } from './api'

const Ctx = createContext(null)
export const useAuth = () => useContext(Ctx)

export const HO = ['L1', 'L2', 'L3']
export const ADMIN = ['SUPER_ADMIN', 'HO_ADMIN']
export const isBranch = u => u && ['BRANCH_ADMIN', 'BRANCH_STAFF'].includes(u.role)
export const isAdmin = u => u && ADMIN.includes(u.role)
export const isHO = u => u && (HO.includes(u.role) || isAdmin(u))

export function AuthProvider({ children }) {
  const [user, setUser] = useState(undefined)   // undefined = loading
  useEffect(() => { refresh().then(u => setUser(u || null)) }, [])
  const login = async (username, password) => {
    const d = await api('/auth/login', { method: 'POST', body: { username, password } })
    setSession(d); setUser(d.user)
  }
  const logout = async () => {
    const t = localStorage.getItem('sk_refresh')
    if (t) try { await api('/auth/logout', { method: 'POST', body: { refresh_token: t } }) } catch {}
    clearSession(); setUser(null)
  }
  return <Ctx.Provider value={{ user, login, logout }}>{children}</Ctx.Provider>
}
