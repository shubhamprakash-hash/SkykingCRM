# Skyking Complaint CRM

One platform for every Skyking branch in India: complaint registration (WhatsApp, email, phone, branch), L1 → L2 → L3
escalation with a 6-hour automatic trigger, de-escalation, branch assignment with deadlines, a branch ⇄ Head Office
chat, and branch-run staff onboarding. Built from the approved blueprint (`docs/Skyking_CRM_Project_Documentation_v0.1.docx`).

## Quick start (development, SQLite, no Docker)

```bash
# backend
cd backend
pip install -r requirements-dev.txt
export ADMIN_EMAIL=you@skyking.in ADMIN_PASSWORD='Choose-a-strong-1'
python -m app.seed --demo          # creates admin, categories, sample branches/users/complaints (prints demo password once)
uvicorn app.main:app --reload      # API on :8000 (docs at /docs)
python -m app.worker               # second terminal: SLA scanner + intake + outbox

# frontend
cd ../frontend && npm install && npm run dev     # http://localhost:5173 (proxies /api to :8000)
```
Demo logins end in `@skyking.demo` (e.g. `priya.l1@skyking.demo`, `neha.l2@…`, `vikram.l3@…`, `anil.mumbai.admin@…`).

## Production (Docker + PostgreSQL)

```bash
cp .env.example .env   # fill every value
docker compose up -d --build
docker compose exec api python -m app.seed       # first admin + categories
```
The `api` container runs `alembic upgrade head` on start and serves the React app and API on :8000; put it behind HTTPS
(nginx / cloud load balancer). The `worker` container runs the SLA scanner and channel pollers. Use a managed PostgreSQL
in an Indian region, daily backups, and monitor the worker's `HEARTBEAT` log line.

## Tests

```bash
cd backend && python -m pytest -q      # 98 tests, ~25 s
```
Highlights: every pair of statuses is checked against the allowed-transition table; a randomized walk (25 seeds × 70 steps)
asserts the invariants (one level per status, every action audited, nothing without a timer or owner); SLA tests use a
simulated clock (working hours, nights, pauses, repeated scanner runs); branch-isolation tests (HTTP 404, no information leak).

## Layout
```
backend/app/services/workflow.py   the state machine: ALLOWED transitions, every action, de-escalation, branch flow
backend/app/services/sla.py        automatic escalation scanner, warnings, daily integrity check
backend/app/services/access.py     the single place that decides who can see which complaint
backend/app/services/intake_*.py   WhatsApp (MSG91) and email intake, threading, de-duplication
backend/app/services/onboarding.py invitations, approvals, staff status, branch CSV import
backend/app/routers/               REST API (OpenAPI at /docs)
frontend/src/pages/                React app (HO + mobile-friendly branch screens)
```

## Rules at a glance (all configurable under Rules & SLA)
* Unattended 6 h (working hours Mon–Sat 09:00–19:00 IST, critical 2 h) → auto-escalate; warning at 80 %.
* L2 chooses per complaint: resolve, assign to a branch (own deadline 2–48 h, ≤2 extensions), or escalate to L3.
  Branch misses its deadline → L3 automatically (or alert L2 only, by setting).
* Send-back L3 → L2 and L2 → L1 needs a reason and a ≥20-character handover note; fresh clock; cooling rule; max 2 send-backs; Admin can override.
* Phone-call complaints: agents create tickets manually (duplicate check, resolve-on-call, call reference).
* Branches register + forward complaints, work assigned ones, chat with HO per complaint and via a help desk, and onboard their own staff.

## Before go-live (not done in this repo — needs Skyking's accounts / decisions)
1. **MSG91:** confirm endpoint paths, webhooks and the outbound-message template API (`services/msg91_client.py` is the only file to change), then set `USE_MOCK_MSG91=false`.
2. **Email:** provide the complaints mailbox (IMAP) or an inbound-mail webhook; outbound email (SMTP) delivery is stubbed in `services/outbox.py`.
3. **MFA** for admin roles and OTP sign-in for branch staff are designed but not built; refresh tokens are stored in the browser's localStorage (move to httpOnly cookies if policy requires).
4. **Virus scanning** of uploads (hook: `Attachment.scan_status`), object storage (uploads use local disk/volume), real-time push (the UI polls every 10–30 s).
5. **Penetration test, load test, DPDP-Act legal review, backup/restore drill** (Section 6.10 of the blueprint).
6. Open decisions in blueprint Section 12 (e.g. SLA clock hours, who may close, retention) — current values are the proposed defaults.
