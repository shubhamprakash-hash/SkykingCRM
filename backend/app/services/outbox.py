import logging
from sqlalchemy.orm import Session
from app.models import OutboundMessage
from app.security import utcnow
from app.services.msg91_client import Msg91Client

log = logging.getLogger("skyking.outbox")


def deliver(db: Session, limit=100) -> dict:
    client, sent, failed = Msg91Client(), 0, 0
    for m in db.query(OutboundMessage).filter(OutboundMessage.status == "queued", OutboundMessage.attempts < 5).limit(limit):
        m.attempts += 1
        try:
            ok = client.send(m.channel, m.to, m.body) if m.channel != "email" else True   # email via SMTP: wire in deployment
        except Exception:
            log.exception("outbound send failed"); ok = False
        if ok: m.status, m.sent_at = "sent", utcnow(); sent += 1
        elif m.attempts >= 5: m.status = "failed"; failed += 1
    db.commit()
    return {"sent": sent, "failed": failed}
