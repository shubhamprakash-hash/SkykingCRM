import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { store } from '../data/store'
import './Home.css'

const DEMO_ACCOUNTS = [
  { role: 'Admin', email: 'admin@skyking.co', password: 'ChangeMe123!' },
  { role: 'Support', email: 'shubham@skyking.co', password: 'demo123' },
  { role: 'L1', email: 'rahul@skyking.co', password: 'demo123' },
  { role: 'L2', email: 'priya.l2@skyking.co', password: 'demo123' },
  { role: 'L3', email: 'meera.l3@skyking.co', password: 'demo123' },
]

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const navigate = useNavigate()

  const submit = (e) => {
    e.preventDefault()
    setError('')
    try {
      const user = store.login(email, password)
      localStorage.setItem('skyking_user', JSON.stringify(user))
      navigate('/dashboard')
    } catch (err) {
      setError(err.message)
    }
  }

  const fillDemo = (acc) => {
    setEmail(acc.email)
    setPassword(acc.password)
  }

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--sk-navy)', fontFamily: 'var(--font-body)', position: 'relative', padding: '40px 20px',
    }}>
      <div style={{
        position: 'absolute', inset: 0,
        background: 'radial-gradient(circle at 20% 15%, rgba(26,86,219,0.35), transparent 45%), radial-gradient(circle at 85% 85%, rgba(230,57,70,0.2), transparent 45%)',
      }} />
      <Link to="/" style={{
        position: 'absolute', top: 28, left: 40, fontFamily: 'var(--font-display)', fontWeight: 700,
        fontSize: 18, color: '#fff', textDecoration: 'none', zIndex: 1,
      }}>
        <span style={{ color: 'var(--sk-red)' }}>Sky</span>King <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: '#8FA3D9', fontWeight: 600 }}>CRM</span>
      </Link>

      <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start', position: 'relative', zIndex: 1, flexWrap: 'wrap', justifyContent: 'center' }}>
        <form onSubmit={submit} style={{
          background: '#fff', padding: 40, borderRadius: 16, width: 360,
          boxShadow: '0 30px 70px -20px rgba(0,0,0,0.5)',
        }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sk-red)', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 600, marginBottom: 8 }}>
            Agent console
          </div>
          <h2 style={{ fontFamily: 'var(--font-display)', margin: '0 0 24px', color: 'var(--sk-navy)', fontSize: 22 }}>
            Log in to continue
          </h2>
          <label style={{ display: 'block', fontSize: 12, color: 'var(--sk-muted)', marginBottom: 6 }}>Email</label>
          <input value={email} onChange={e => setEmail(e.target.value)} placeholder="admin@skyking.co"
            style={{ width: '100%', padding: '11px 12px', marginBottom: 16, boxSizing: 'border-box', border: '1px solid #E7ECF7', borderRadius: 8, fontSize: 14 }} />
          <label style={{ display: 'block', fontSize: 12, color: 'var(--sk-muted)', marginBottom: 6 }}>Password</label>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••"
            style={{ width: '100%', padding: '11px 12px', marginBottom: 16, boxSizing: 'border-box', border: '1px solid #E7ECF7', borderRadius: 8, fontSize: 14 }} />
          {error && <div style={{ color: 'var(--sk-red)', fontSize: 13, marginBottom: 16 }}>{error}</div>}
          <button type="submit" style={{
            width: '100%', padding: 13, background: 'var(--sk-blue)', color: '#fff', border: 'none',
            borderRadius: 8, cursor: 'pointer', fontWeight: 600, fontSize: 14,
          }}>
            Log in
          </button>
        </form>

        <div style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: 16, padding: 24, width: 280 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: '#8FA3D9', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 600, marginBottom: 14 }}>
            Demo accounts
          </div>
          {DEMO_ACCOUNTS.map(acc => (
            <button key={acc.email} onClick={() => fillDemo(acc)} style={{
              display: 'block', width: '100%', textAlign: 'left', background: 'rgba(255,255,255,0.04)',
              border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, padding: '10px 12px', marginBottom: 8,
              cursor: 'pointer', color: '#fff', fontFamily: 'var(--font-mono)', fontSize: 12,
            }}>
              <div style={{ fontWeight: 600, color: 'var(--sk-amber)' }}>{acc.role}</div>
              <div style={{ color: '#B9C4E6' }}>{acc.email}</div>
            </button>
          ))}
          <div style={{ fontSize: 11, color: '#8FA3D9', marginTop: 8 }}>Click one to autofill, then Log in.</div>
        </div>
      </div>
    </div>
  )
}
