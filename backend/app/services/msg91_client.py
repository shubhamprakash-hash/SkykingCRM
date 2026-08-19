"""
Thin wrapper around the MSG91 Hello REST API. The authkey lives only in
backend env vars (app.core.config) and is never returned to the frontend.

This client is intentionally SYNCHRONOUS (httpx.Client, not AsyncClient).
sync_tickets() needs to run both from plain scripts (app/seed.py) and from
inside FastAPI's own async lifespan/scheduler context -- mixing a nested
asyncio event loop into an already-running one throws
"RuntimeError: This event loop is already running". A synchronous client
sidesteps that entirely and is fine here since MSG91 sync is not on any
user-facing request path.

MOCK MODE: while settings.USE_MOCK_MSG91 is True, get_tickets() reads from
the local fixture at settings.MOCK_MSG91_FILE (the sample payload you
provided) instead of calling MSG91 live. This lets the whole CRM -- sync,
eligibility filtering, dashboard, escalation flow -- be built and tested
today without live API access.

TO SWITCH TO THE REAL API: once you have MSG91 credentials, set
USE_MOCK_MSG91=false and MSG91_AUTHKEY=<your key> in .env. Nothing else in
the codebase needs to change -- sync_service.py only ever calls
Msg91Client.get_tickets(), never the mock file directly.

NOTE: endpoint paths below follow MSG91 Hello's documented API shape
(Get Tickets / Get Ticket Messages). Confirm exact paths/params against
current MSG91 Hello API docs before go-live -- MSG91 has been known to
version these; this client isolates that surface so a path change is a
one-file edit.
"""
import json
from pathlib import Path
from typing import Optional
import httpx
from app.core.config import get_settings

settings = get_settings()


class Msg91Client:
    def __init__(self):
        self.base_url = settings.MSG91_BASE_URL
        self.headers = {
            "authkey": settings.MSG91_AUTHKEY,
            "Content-Type": "application/json",
        }

    def get_tickets(self, page: int = 1, per_page: int = 50, updated_since: Optional[str] = None) -> dict:
        if settings.USE_MOCK_MSG91:
            return self._mock_get_tickets(page)

        params = {"page": page, "per_page": per_page}
        if updated_since:
            params["updated_since"] = updated_since
        with httpx.Client(timeout=30) as client:
            resp = client.get(f"{self.base_url}/tickets", headers=self.headers, params=params)
            resp.raise_for_status()
            return resp.json()

    def _mock_get_tickets(self, page: int) -> dict:
        # Only page 1 has data; any further page returns empty so
        # sync_service's pagination loop stops naturally.
        if page > 1:
            return {"chat_channels": [], "total_ticket_count": 0}
        path = Path(settings.MOCK_MSG91_FILE)
        if not path.is_absolute():
            # resolve relative to the backend/ directory (repo root for this app)
            path = Path(__file__).resolve().parents[2] / settings.MOCK_MSG91_FILE
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_ticket_messages(self, chat_id: str, session_id: Optional[str] = None) -> dict:
        if settings.USE_MOCK_MSG91:
            # Mock: synthesize a short thread from the ticket's last_message
            # so the conversation UI has something to render in dev mode.
            data = self._mock_get_tickets(1)
            for ch in data.get("chat_channels", []):
                if str(ch.get("id")) == str(chat_id):
                    return {"messages": [ch["last_message"]["message"]]}
            return {"messages": []}

        params = {"chat_id": chat_id}
        if session_id:
            params["session_id"] = session_id
        with httpx.Client(timeout=30) as client:
            resp = client.get(f"{self.base_url}/messages", headers=self.headers, params=params)
            resp.raise_for_status()
            return resp.json()

    def assign_ticket(self, ticket_id: int, assignee_type: str, assignee_id: str) -> dict:
        if settings.USE_MOCK_MSG91:
            return {"status": "mocked", "ticket_id": ticket_id}

        payload = {"ticket_id": ticket_id, "assignee_type": assignee_type, "assignee_id": assignee_id}
        with httpx.Client(timeout=30) as client:
            resp = client.put(f"{self.base_url}/assign", headers=self.headers, json=payload)
            resp.raise_for_status()
            return resp.json()
