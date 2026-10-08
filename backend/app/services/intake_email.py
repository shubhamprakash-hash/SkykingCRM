"""Email intake: raw RFC-822 -> new complaint, or a reply attached to an existing one (threading)."""
import email, imaplib, os, re, uuid
from email import policy
from email.utils import parseaddr
from pathlib import Path
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models import EmailMessage, Ticket, Attachment
from app.services import workflow as wf

NUM = re.compile(r"CRM-\d{7}")
SKIP_SENDERS = re.compile(r"(mailer-daemon|postmaster|no-?reply|donotreply)", re.I)
ALLOWED_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".txt", ".doc", ".docx", ".xls", ".xlsx", ".csv"}


def is_automatic(msg) -> bool:
    if str(msg.get("Auto-Submitted", "no")).lower() != "no": return True
    if str(msg.get("Precedence", "")).lower() in ("bulk", "junk", "list"): return True
    if msg.get("X-Autoreply") or msg.get("X-Autorespond"): return True
    addr = parseaddr(msg.get("From", ""))[1]
    subj = str(msg.get("Subject", ""))
    return bool(SKIP_SENDERS.search(addr)) or subj.lower().startswith(("undeliverable", "delivery status", "automatic reply"))


def _body(msg) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    text = part.get_content() if part else ""
    if part and part.get_content_type() == "text/html":
        text = re.sub(r"<[^>]+>", " ", text)
    # drop quoted history
    cut = re.split(r"\n(On .+ wrote:|-----Original Message-----|From: .+\nSent:)", text, maxsplit=1)[0]
    return re.sub(r"[ \t]+\n", "\n", cut).strip()


def _save_attachments(db, msg, ticket):
    base = Path(get_settings().UPLOAD_DIR); base.mkdir(parents=True, exist_ok=True)
    for part in msg.iter_attachments():
        name = os.path.basename(part.get_filename() or "attachment")
        if Path(name).suffix.lower() not in ALLOWED_EXT: continue
        data = part.get_content()
        data = data.encode() if isinstance(data, str) else data
        if len(data) > get_settings().MAX_UPLOAD_MB * 1024 * 1024: continue
        path = base / f"{uuid.uuid4().hex}{Path(name).suffix.lower()}"
        path.write_bytes(data)
        db.add(Attachment(ticket_id=ticket.id, filename=name, content_type=part.get_content_type(), size=len(data),
                          storage_path=str(path)))


def process_raw_email(db: Session, raw: bytes, now=None) -> dict:
    msg = email.message_from_bytes(raw, policy=policy.default)
    mid = (msg.get("Message-ID") or "").strip()
    if not mid: mid = f"<generated-{uuid.uuid4().hex}@skyking>"
    if db.query(EmailMessage).filter_by(message_id=mid).first():
        return {"result": "duplicate"}
    if is_automatic(msg):
        return {"result": "ignored_automatic"}
    sender = parseaddr(msg.get("From", ""))[1].lower()
    subject, body = str(msg.get("Subject", "")).strip(), _body(msg) or "(no text)"
    refs = " ".join([str(msg.get("In-Reply-To", "")), str(msg.get("References", ""))]).split()
    ticket = None
    if refs:
        em = db.query(EmailMessage).filter(EmailMessage.message_id.in_(refs), EmailMessage.ticket_id.isnot(None)).first()
        if em: ticket = db.get(Ticket, em.ticket_id)
    if ticket is None:
        n = NUM.search(subject)
        if n: ticket = db.query(Ticket).filter_by(number=n.group(0)).first()
    if ticket is not None:
        outcome = wf.customer_reply(db, ticket, body, now=now)
        db.add(EmailMessage(message_id=mid, ticket_id=ticket.id, from_addr=sender, subject=subject)); db.flush()
        _save_attachments(db, msg, ticket)
        return {"result": f"reply_{outcome}", "ticket": ticket.number}
    ticket = wf.create_ticket(db, None, source="email", description=body, subject=subject or body[:80], email=sender,
                              name=parseaddr(msg.get("From", ""))[0] or None, allow_duplicate=True, now=now)
    db.add(EmailMessage(message_id=mid, ticket_id=ticket.id, from_addr=sender, subject=subject)); db.flush()
    _save_attachments(db, msg, ticket)
    return {"result": "created", "ticket": ticket.number}


def poll_imap(db: Session) -> dict:
    s = get_settings()
    if not (s.IMAP_HOST and s.IMAP_USER): return {"skipped": "IMAP not configured"}
    out = {"created": 0, "reply": 0, "other": 0}
    with imaplib.IMAP4_SSL(s.IMAP_HOST) as box:
        box.login(s.IMAP_USER, s.IMAP_PASSWORD); box.select(s.IMAP_FOLDER)
        _, data = box.search(None, "UNSEEN")
        for num in data[0].split():
            _, parts = box.fetch(num, "(RFC822)")
            res = process_raw_email(db, parts[0][1])["result"]
            db.commit()
            out["created" if res == "created" else "reply" if res.startswith("reply") else "other"] += 1
            box.store(num, "+FLAGS", "\\Seen")
    return out
