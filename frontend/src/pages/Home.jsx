import { useNavigate } from 'react-router-dom'
import './Home.css'

const STOPS = [
  { code: 'L0', label: 'Support', active: true },
  { code: 'L1', label: 'L1 Escalation', active: false },
  { code: 'L2', label: 'L2 Escalation', active: false },
  { code: 'L3', label: 'L3 — Final', active: false },
]

const FEATURES = [
  {
    n: '01',
    title: 'WhatsApp intake via MSG91',
    body: 'Only conversations assigned to the Support Team inbox enter the queue — bot chats and unassigned threads never clutter the CRM.',
  },
  {
    n: '02',
    title: 'L0 → L1 → L2 → L3 routing',
    body: 'Every ticket moves one level at a time, worked by the role that owns that level. No level gets skipped without an Admin override.',
  },
  {
    n: '03',
    title: 'Consignment-linked customers',
    body: 'Customers, their shipments, and every ticket they\'ve raised stay connected — one lookup shows the whole history.',
  },
  {
    n: '04',
    title: 'An audit trail that never forgets',
    body: 'Pick, comment, escalate, resolve, close — every action is timestamped and attributed, permanently.',
  },
]

export default function Home() {
  const navigate = useNavigate()

  return (
    <div className="home">
      <nav className="home-nav">
        <div className="home-logo">
          <span className="mark">Sky</span><span className="rest">King</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: '#8FA3D9', marginLeft: 4, fontWeight: 600 }}>CRM</span>
        </div>
        <div className="home-nav-links">
          <a href="#flow">Escalation Flow</a>
          <a href="#features">Features</a>
        </div>
        <button className="home-cta" onClick={() => navigate('/login')}>Log in</button>
      </nav>

      <section className="hero">
        <div>
          <div className="hero-eyebrow">Ticket Escalation Console</div>
          <h1>Every WhatsApp complaint,<br /><span>tracked to resolution.</span></h1>
          <p className="lead">
            SkyKing's support desk for consignment issues raised over WhatsApp —
            claimed by an agent, escalated only when it needs to be, and never
            without a record of who did what and when.
          </p>
          <div className="hero-actions">
            <button className="hero-primary-btn" onClick={() => navigate('/login')}>Open the console</button>
            <a className="hero-secondary" href="#flow">See how escalation works ↓</a>
          </div>
          <div className="hero-stats">
            <div className="hero-stat"><b>1,600+</b><span>Distribution points</span></div>
            <div className="hero-stat"><b>1,25,000</b><span>Shipments / day</span></div>
            <div className="hero-stat"><b>4</b><span>Escalation levels</span></div>
          </div>
        </div>

        <div className="route-card" id="flow">
          <div className="route-label">Ticket #CRM-0000182 — live path</div>
          <div className="route-ticket">
            <span>Kiran Baheti · Consignment 3307260346</span>
            <span className="status">picked · L1</span>
          </div>
          <div className="route-path">
            <div className="route-line" />
            <div className="route-line-fill" />
            <div className="route-stops">
              {STOPS.map(s => (
                <div key={s.code} className={`route-stop ${s.code === 'L1' ? 'active' : ''}`}>
                  <div className="route-dot">{s.code}</div>
                  <div className="route-stop-label">{s.label}</div>
                </div>
              ))}
            </div>
          </div>
          <div className="route-footer">
            <span>PICKED 11:52</span>
            <span>ESCALATED 12:08</span>
            <span>AWAITING L1</span>
          </div>
        </div>
      </section>

      <section className="features" id="features">
        <div className="features-head">
          <div className="kicker">Built for the support desk</div>
          <h2>Four things it does, and does properly.</h2>
        </div>
        <div className="features-grid">
          {FEATURES.map(f => (
            <div className="feature-card" key={f.n}>
              <div className="feature-num">{f.n}</div>
              <h3>{f.title}</h3>
              <p>{f.body}</p>
            </div>
          ))}
        </div>
      </section>

      <footer className="home-footer">
        <span><b>SkyKing</b> — Your Delivery Partner, Since 1976</span>
        <span>Internal CRM prototype</span>
      </footer>
    </div>
  )
}
