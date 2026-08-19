# SkyKing CRM — Ticket Escalation Management System

A working scaffold implementing the spec: MSG91 Hello WhatsApp ticket ingestion,
role-based L0(Support)→L1→L2→L3 escalation workflow, full audit trail, and a
React dashboard.

## Architecture

```
React Frontend (Vite)
      |  /api/* (JWT bearer)
      v
FastAPI Backend
      |                    \
      v                     v
PostgreSQL/MySQL      MSG91 Hello API
(SQLAlchemy models)   (authkey server-side only, app/services/msg91_client.py)
```

## What's implemented

**Backend** (`backend/app`)
- `models/models.py` — full relational schema: `users`, `roles`,
  `system_config`, `customers`, `consignments`, `msg91_tickets`,
  `msg91_messages`, `tickets`, `ticket_assignments`, `ticket_comments`,
  `escalations`, `ticket_history`. Uses `msg91_ticket_id` as the external
  key so re-syncing never duplicates a ticket (spec §17).
- `services/config_service.py` — the eligibility rule (origin=whatsapp,
  inbox_id=2271, assignee_type=team, assignee_id=2253) lives in a DB
  `system_config` table, not hardcoded, editable by Admins at runtime
  (spec §21).
- `services/msg91_client.py` — MSG91 Hello API wrapper. Authkey is read
  from a backend-only env var and never sent to the frontend.
- `services/sync_service.py` — fetches, filters, and upserts tickets.
  Runs on a scheduled interval via APScheduler (see `main.py` lifespan)
  and can also be triggered manually from the dashboard's Refresh/Sync
  button.
- `services/escalation_service.py` — the L0→L1→L2→L3 state machine.
  Enforces that only the role matching the current level (or an Admin)
  can act on a ticket, and that levels can't be skipped unless an Admin
  explicitly forces it. Every action writes one `ticket_history` row.
- `routers/` — `auth` (JWT login), `tickets` (list/filter/search/pick/
  resolution-form/comments/escalate/resolve/close/reassign/sync),
  `dashboard` (role-specific summary counts per spec §18), `customers`
  (customer profile with linked tickets & consignments, spec §12).

**Frontend** (`frontend/src`)
- Login → JWT stored client-side, attached via axios interceptor.
- Sidebar layout matching spec §19 (Dashboard / Available / My Tickets /
  L1 / L2 / L3 / Resolved / Customers).
- `TicketList` — one component parameterized per queue, with search,
  Pick Ticket action, priority coloring, unread badges, Refresh/Sync.
- `TicketDetail` — the resolution workspace: customer/consignment form,
  WhatsApp last-message preview, comments thread, escalate/resolve/close
  actions gated by ticket state, and the full audit history timeline.

## What's a stub / needs your input before production

1. **MSG91 endpoint paths** in `msg91_client.py` (`/tickets`, `/messages`,
   `/assign`) are written to the documented Hello API shape but should be
   confirmed against MSG91's current docs — I don't have your account's
   live API reference to verify exact paths/params.
2. **Full WhatsApp conversation history** (spec §11) — the scaffold
   stores `last_message` from the ticket list payload. Pulling the
   *complete* thread needs MSG91's messages-by-chat_id endpoint; the
   `Msg91Message` table and `get_ticket_messages()` client method are
   ready for this, just needs wiring into the sync loop.
3. **Password reset / user management UI** for Admin — backend model
   supports it (`users`, `roles`), no endpoints/UI yet.
4. **Priority auto-escalation timers**, **date-range filters**, and
   **Excel/PDF report export** (spec §14–15, §18 "View reports") aren't
   built yet — straightforward additions on top of the existing ticket
   query.
5. Alembic migrations aren't set up — `Base.metadata.create_all` runs on
   startup for now, fine for initial development, replace before prod.

## Running locally

```bash
# Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in MSG91_AUTHKEY and a real SECRET_KEY
# create the postgres db first: createdb skyking_crm
python -m app.seed      # creates roles + admin@skyking.co / ChangeMe123!
uvicorn app.main:app --reload

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Then open http://localhost:5173, log in as `admin@skyking.co` /
`ChangeMe123!`, and change that password immediately.

## This version: standalone frontend, no backend needed

Per your request, this build stores all data client-side -- in the
browser's `localStorage` -- seeded from the same MSG91 sample tickets.
There's no server, no database, no environment variables, no CORS, no
seeding step. You can deploy `frontend/` alone as a static site anywhere
(Render Static Site, Netlify, Vercel, GitHub Pages) and it just works.

**Demo accounts** (shown on the login page -- click one to autofill):
| Role | Email | Password |
|---|---|---|
| Admin | admin@skyking.co | ChangeMe123! |
| Support | shubham@skyking.co | demo123 |
| L1 | rahul@skyking.co | demo123 |
| L2 | priya.l2@skyking.co | demo123 |
| L3 | meera.l3@skyking.co | demo123 |

**What's in `frontend/src/data/`:**
- `seedData.js` -- the 5 tickets that pass the eligibility filter from
  your MSG91 sample (same ones the backend's sync would produce), plus
  the 5 demo users.
- `store.js` -- replicates the backend's `escalation_service.py` logic
  exactly: one level at a time, role-gated actions (only the role
  matching a ticket's current level, or Admin, can act on it), full audit
  history, L3/Admin-only close. Every mutation persists to
  `localStorage` under `skyking_crm_store_v1`, so state survives a page
  refresh.
- Data is scoped to one browser -- there's no sharing across users/tabs/
  devices, since there's no server. Each person who opens the deployed
  link gets their own independent copy of the demo data.
- The sidebar has a **"Reset demo data"** button (bottom left) to wipe
  everything back to the original 5 tickets.

**To run locally:**
```bash
cd frontend
npm install
npm run dev
```
No `.env`, no backend terminal needed.

**To deploy:** any static host works. On Render: New -> Static Site ->
Root Directory `frontend` -> Build Command `npm install && npm run build`
-> Publish Directory `dist`. Add a rewrite rule (`/*` -> `/index.html`,
Action: Rewrite) so client-side routes like `/dashboard` don't 404 on
direct load/refresh -- that's the only config needed, no env vars.

## The full-stack version (backend/) is still here, for later

`backend/` (FastAPI + the same escalation logic + MSG91 sync) is
untouched and still in this zip. When you're ready to move past the
prototype stage -- real MSG91 credentials, a shared database, multiple
people seeing the same live ticket state -- that's the version to deploy
instead, following the earlier backend deployment steps. Nothing here
changes that path; this is purely an easier-to-demo alternative for now.
