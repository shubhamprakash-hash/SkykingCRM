"""WhatsApp intake: MSG91 tickets -> CRM complaints (de-duplicated by MSG91 ticket id)."""
from sqlalchemy.orm import Session
from app.models import ExternalRef, Ticket, Setting
from app.services import workflow as wf
from app.services.msg91_client import Msg91Client

SRC = "msg91"
DEFAULT_RULE = {"origin": "whatsapp", "inbox_ids": [], "assignee_type": None, "assignee_ids": []}   # empty list = any


def rule(db: Session) -> dict:
    row = db.get(Setting, "msg91_rule")
    return {**DEFAULT_RULE, **((row.value if row else None) or {})}


def eligible(raw: dict, r: dict) -> bool:
    if r["origin"] and raw.get("origin") != r["origin"]: return False
    inboxes = [i.get("inbox_id") for i in raw.get("inbox_ids", [])]
    if r["inbox_ids"] and not set(r["inbox_ids"]) & set(inboxes): return False
    if r["assignee_type"] and str(raw.get("assignee_type")) != r["assignee_type"]: return False
    if r["assignee_ids"] and str(raw.get("assignee_id")) not in [str(x) for x in r["assignee_ids"]]: return False
    return True


def _last_text(raw):
    m = (raw.get("last_message") or {}).get("message") or {}
    return (m.get("content") or {}).get("text"), m.get("message_id"), m.get("sender_id")


def ingest(db: Session, raw: dict, now=None) -> str:
    """Create a complaint, or attach the newest customer message to the existing one. Returns what happened."""
    ext = str(raw["ticket_id"])
    text, mid, sender = _last_text(raw)
    ref = db.query(ExternalRef).filter_by(source=SRC, external_id=ext).first()
    from_customer = sender not in ("bot", None) and not str(sender).startswith("agent")
    if ref is None:
        desc = (text or "WhatsApp complaint").strip()
        t = wf.create_ticket(db, None, source="whatsapp", description=desc, mobile=raw.get("customer_number"),
                             name=raw.get("customer_name"), email=raw.get("customer_mail"), allow_duplicate=True, now=now)
        db.add(ExternalRef(source=SRC, external_id=ext, ticket_id=t.id, marker=mid)); db.flush()
        return "created"
    if mid and ref.marker != mid:
        ref.marker = mid
        if from_customer and text:
            t = db.get(Ticket, ref.ticket_id)
            wf.customer_reply(db, t, text, now=now)
            return "reply"
    return "unchanged"


def sync(db: Session, pages=3, per_page=100, now=None) -> dict:
    r, client, out = rule(db), Msg91Client(), {"created": 0, "reply": 0, "unchanged": 0, "skipped": 0}
    for page in range(1, pages + 1):
        data = client.get_tickets(page=page, per_page=per_page)
        chans = data.get("chat_channels", [])
        if not chans: break
        for raw in chans:
            if not eligible(raw, r): out["skipped"] += 1; continue
            out[ingest(db, raw, now)] += 1
    db.commit()
    return out
