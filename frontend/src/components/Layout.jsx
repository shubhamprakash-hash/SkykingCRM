import { NavLink, useNavigate } from 'react-router-dom'
import { store } from '../data/store'

const items = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/tickets/available', label: 'Available Tickets' },
  { to: '/tickets/mine', label: 'My Tickets' },
  { to: '/tickets/l1', label: 'L1 Escalations' },
  { to: '/tickets/l2', label: 'L2 Escalations' },
  { to: '/tickets/l3', label: 'L3 Escalations' },
  { to: '/tickets/resolved', label: 'Resolved' },
  { to: '/customers', label: 'Customers' },
]

export default function Layout({ children }) {
  const navigate = useNavigate()
  const user = JSON.parse(localStorage.getItem('skyking_user') || 'null')

  const logout = () => {
    localStorage.removeItem('skyking_user')
    navigate('/login')
  }

  const resetData = () => {
    if (confirm('Reset all demo tickets back to their original state? This clears anything picked/escalated/resolved in this browser.')) {
      store.resetDemoData()
      window.location.reload()
    }
  }

  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <div style={{ width: 220, background: '#111827', color: '#fff', padding: '20px 0', flexShrink: 0 }}>
        <div style={{ padding: '0 20px 20px', fontWeight: 700, fontSize: 18, color: '#60a5fa' }}>SkyKing CRM</div>
        {items.map(i => (
          <NavLink key={i.to} to={i.to}
            style={({ isActive }) => ({
              display: 'block', padding: '10px 20px', color: isActive ? '#fff' : '#9ca3af',
              background: isActive ? '#1f2937' : 'transparent', textDecoration: 'none', fontSize: 14,
            })}>
            {i.label}
          </NavLink>
        ))}
        <div style={{ padding: '20px 20px 0', marginTop: 20, borderTop: '1px solid #374151' }}>
          <div style={{ color: '#6b7280', fontSize: 12, marginBottom: 2 }}>{user?.name}</div>
          <div style={{ color: '#6b7280', fontSize: 12, marginBottom: 8, textTransform: 'uppercase' }}>Role: {user?.role || 'unknown'}</div>
          <button onClick={logout} style={{ background: 'none', border: '1px solid #374151', color: '#9ca3af', padding: '6px 12px', borderRadius: 4, cursor: 'pointer', marginRight: 8, marginBottom: 8 }}>
            Log out
          </button>
          <button onClick={resetData} style={{ display: 'block', background: 'none', border: '1px solid #374151', color: '#6b7280', padding: '6px 12px', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}>
            Reset demo data
          </button>
        </div>
      </div>
      <div style={{ flex: 1, padding: 24 }}>{children}</div>
    </div>
  )
}
