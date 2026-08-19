import { useEffect, useState } from 'react'
import Layout from '../components/Layout'
import { store } from '../data/store'

export default function Dashboard() {
  const [summary, setSummary] = useState({})

  useEffect(() => {
    const user = JSON.parse(localStorage.getItem('skyking_user') || 'null')
    if (user) setSummary(store.dashboardSummary(user))
  }, [])

  const cardStyle = { background: '#fff', borderRadius: 8, padding: 20, minWidth: 160, boxShadow: '0 1px 4px rgba(0,0,0,0.06)' }

  return (
    <Layout>
      <h2>Dashboard</h2>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        {Object.entries(summary).map(([key, value]) => (
          <div key={key} style={cardStyle}>
            <div style={{ fontSize: 28, fontWeight: 700, color: '#1a56db' }}>{value}</div>
            <div style={{ color: '#6b7280', fontSize: 13, textTransform: 'capitalize' }}>
              {key.replace(/_/g, ' ')}
            </div>
          </div>
        ))}
      </div>
    </Layout>
  )
}
