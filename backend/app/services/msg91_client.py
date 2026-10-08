"""
Thin, synchronous wrapper around the MSG91 Hello API. The authkey stays server-side.
Mock mode (USE_MOCK_MSG91=true) reads the sample payload so everything can run without credentials.

BEFORE GO-LIVE: confirm endpoint paths/params and webhook availability against the live MSG91 Hello docs and the
Skyking account. This file is the only place that knows those paths.
"""
import json
from pathlib import Path
import httpx
from app.config import get_settings


class Msg91Client:
    def __init__(self):
        self.s = get_settings()
        self.headers = {"authkey": self.s.MSG91_AUTHKEY, "Content-Type": "application/json"}

    def get_tickets(self, page=1, per_page=50) -> dict:
        if self.s.USE_MOCK_MSG91:
            if page > 1: return {"chat_channels": [], "total_ticket_count": 0}
            p = Path(self.s.MOCK_MSG91_FILE)
            if not p.is_absolute(): p = Path(__file__).resolve().parents[2] / self.s.MOCK_MSG91_FILE
            return json.loads(p.read_text(encoding="utf-8"))
        with httpx.Client(timeout=30) as c:
            r = c.get(f"{self.s.MSG91_BASE_URL}/tickets", headers=self.headers, params={"page": page, "per_page": per_page})
            r.raise_for_status(); return r.json()

    def send(self, channel: str, to: str, body: str) -> bool:
        """Deliver an outbound customer message. Returns True when accepted."""
        if self.s.USE_MOCK_MSG91 or not self.s.MSG91_SEND_URL:
            return True
        with httpx.Client(timeout=30) as c:
            r = c.post(self.s.MSG91_SEND_URL, headers=self.headers, json={"channel": channel, "to": to, "text": body})
            return r.status_code < 300
