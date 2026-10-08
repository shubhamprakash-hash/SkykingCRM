import uuid
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, func
from sqlalchemy.orm import Session
from app.config import get_settings
from app.database import get_db
from app.deps import current_user
from app.enums import Role, S
from app.models import Ticket, Customer, BranchPincode, Branch, Message, MessageRead, Attachment, User, Notification
from app.security import utcnow
from app.serializers import ticket_out, iso
from app.services import workflow as wf, access
from app.services.errors import NotFound, NotAllowed, ValidationFailed

router = APIRouter(prefix="/api", tags=["tickets"])


def load(db, user, tid) -> Ticket:
    t = db.get(Ticket, tid)
    if not t or not access.can_view(db, user, t):
        raise NotFound("Complaint not found")           # same answer whether it exists or not: no information leak
    return t


@router.get("/tickets")
def list_tickets(q: str | None = None, status: str | None = None, level: int | None = None, branch_id: int | None = None,
                 priority: str | None = None, source: str | None = None, overdue: bool = False, mine: bool = False,
                 queue: bool = False, open_only: bool = False, page: int = 1, size: int = Query(25, le=200),
                 db: Session = Depends(get_db), user: User = Depends(current_user)):
    qry = access.visible_tickets(db, user)
    if q:
        like = f"%{q.strip()}%"
        qry = qry.outerjoin(Customer, Customer.id == Ticket.customer_id).filter(or_(
            Ticket.number.ilike(like), Ticket.subject.ilike(like), Ticket.consignment_no.ilike(like),
            Customer.mobile.ilike(like), Customer.name.ilike(like), Customer.email.ilike(like)))
    if status: qry = qry.filter(Ticket.status == status)
    if level: qry = qry.filter(Ticket.level == level)
    if branch_id: qry = qry.filter(or_(Ticket.branch_id == branch_id, Ticket.origin_branch_id == branch_id))
    if priority: qry = qry.filter(Ticket.priority == priority)
    if source: qry = qry.filter(Ticket.source == source)
    if open_only: qry = qry.filter(Ticket.status.in_(list(S.OPEN)))
    if overdue: qry = qry.filter(Ticket.due_at < utcnow(), Ticket.status.in_(list(S.OPEN)))
    if mine:
        qry = qry.filter(or_(Ticket.owner_id == user.id, Ticket.branch_assignee_id == user.id))
    if queue:
        lvl = wf.user_level(user)
        qry = qry.filter(Ticket.owner_id.is_(None), Ticket.status.in_(list(S.QUEUE.values())))
        if lvl: qry = qry.filter(Ticket.level == lvl)
    total = qry.count()
    rows = qry.order_by(Ticket.due_at.is_(None), Ticket.due_at, Ticket.id.desc()).offset((page - 1) * size).limit(size).all()
    return {"total": total, "page": page, "items": [ticket_out(db, t, user) for t in rows]}


class NewTicket(BaseModel):
    source: str = "phone_inbound"
    description: str
    mobile: str | None = None
    email: str | None = None
    name: str | None = None
    category_id: int | None = None
    subject: str | None = None
    priority: str | None = None
    urgent: bool = False
    mode: str = "queue"                      # queue | take | draft
    level: int | None = None
    allow_duplicate: bool = False
    consignment_no: str | None = None
    receiver_name: str | None = None
    receiver_mobile: str | None = None
    address: str | None = None
    pincode: str | None = None
    preferred_contact: str | None = None
    preferred_language: str | None = None
    caller_number: str | None = None
    call_received_at: datetime | None = None
    call_reference: str | None = None
    resolve: dict | None = None


@router.post("/tickets", status_code=201)
def create(body: NewTicket, db: Session = Depends(get_db), user: User = Depends(current_user)):
    data = body.model_dump()
    t = wf.create_ticket(db, user, **data)
    db.commit()
    return ticket_out(db, t, user, detail=True)


class DupCheck(BaseModel):
    mobile: str | None = None
    email: str | None = None
    consignment_no: str | None = None


@router.post("/tickets/check-duplicate")
def check_duplicate(body: DupCheck, db: Session = Depends(get_db), user: User = Depends(current_user)):
    c = wf.find_customer(db, body.mobile, body.email)
    if not c: return {"customer": None, "open_complaints": [], "duplicates": []}
    open_ = access.visible_tickets(db, user).filter(Ticket.customer_id == c.id, Ticket.status.in_(list(S.OPEN))).all()
    dups = [t for t in open_ if body.consignment_no and t.consignment_no == body.consignment_no]
    brief = lambda t: {"id": t.id, "number": t.number, "status": t.status, "subject": t.subject, "consignment_no": t.consignment_no}
    return {"customer": {"id": c.id, "name": c.name, "mobile": c.mobile, "email": c.email},
            "open_complaints": [brief(t) for t in open_], "duplicates": [brief(t) for t in dups]}


@router.get("/tickets/suggest-branch")
def suggest_branch(pincode: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if user.role in Role.BRANCH: raise NotAllowed("Not allowed")
    rows = db.query(Branch).join(BranchPincode).filter(BranchPincode.pincode == pincode.strip(), Branch.status == "live").all()
    return [{"id": b.id, "code": b.code, "name": b.name, "city": b.city} for b in rows]


@router.get("/tickets/{tid}")
def get_ticket(tid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return ticket_out(db, load(db, user, tid), user, detail=True)


class ActionBody(BaseModel):
    action: str
    version: int | None = None
    params: dict = Field(default_factory=dict)


@router.post("/tickets/{tid}/actions")
def do_action(tid: int, body: ActionBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = load(db, user, tid)
    wf.run_action(db, t, user, body.action, body.params, body.version)
    db.commit()
    return ticket_out(db, t, user, detail=True)


class MsgBody(BaseModel):
    channel: str = "thread"
    body: str


@router.post("/tickets/{tid}/messages", status_code=201)
def post_message(tid: int, body: MsgBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = load(db, user, tid)
    wf.post_message(db, user, t, body.channel, body.body)
    db.commit()
    return ticket_out(db, t, user, detail=True)


@router.post("/messages/{mid}/read")
def mark_read(mid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    msg = db.get(Message, mid)
    if msg and msg.ticket_id:
        load(db, user, msg.ticket_id)
    elif msg and msg.branch_id and not (user.role in Role.ADMIN | Role.HO_LEVEL or user.branch_id == msg.branch_id):
        raise NotFound("Message not found")
    if msg and not db.query(MessageRead).filter_by(message_id=mid, user_id=user.id).first():
        db.add(MessageRead(message_id=mid, user_id=user.id)); db.commit()
    return {"ok": True}


ALLOWED_UPLOAD = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".txt", ".doc", ".docx", ".xls", ".xlsx", ".csv"}


@router.post("/tickets/{tid}/attachments", status_code=201)
async def upload(tid: int, file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = load(db, user, tid)
    if user.role in Role.BRANCH and not access.branch_can_write(db, user, t): raise NotAllowed("Cannot attach to this complaint")
    s = get_settings()
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_UPLOAD: raise ValidationFailed("This file type is not allowed")
    data = await file.read()
    if len(data) > s.MAX_UPLOAD_MB * 1024 * 1024: raise ValidationFailed(f"File larger than {s.MAX_UPLOAD_MB} MB")
    base = Path(s.UPLOAD_DIR); base.mkdir(parents=True, exist_ok=True)
    path = base / f"{uuid.uuid4().hex}{ext}"
    path.write_bytes(data)
    a = Attachment(ticket_id=t.id, filename=Path(file.filename).name, content_type=file.content_type, size=len(data),
                   storage_path=str(path), uploaded_by=user.id)
    db.add(a); db.flush()
    wf.log(db, t, "attachment_added", user, frm=(t.status, t.level), meta={"filename": a.filename})
    db.commit()
    return {"id": a.id, "filename": a.filename, "size": a.size}


@router.get("/attachments/{aid}")
def download(aid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    a = db.get(Attachment, aid)
    if not a: raise NotFound("Not found")
    load(db, user, a.ticket_id)
    return FileResponse(a.storage_path, filename=a.filename, media_type=a.content_type or "application/octet-stream")


# ---------------------------------------------------------------- branch <-> Head Office help desk
class HelpBody(BaseModel):
    body: str
    branch_id: int | None = None


def _help_branch(user, branch_id):
    if user.role in Role.BRANCH:
        return user.branch_id
    if user.role in Role.ADMIN | Role.HO_LEVEL and branch_id:
        return branch_id
    raise ValidationFailed("branch_id is required")


@router.get("/helpdesk")
def helpdesk(branch_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    bid = _help_branch(user, branch_id)
    rows = db.query(Message).filter_by(channel="helpdesk", branch_id=bid, deleted=False).order_by(Message.id.desc()).limit(200).all()[::-1]
    return [{"id": m.id, "author": m.author.name if m.author else "-", "author_role": m.author.role if m.author else None,
             "body": m.body, "at": iso(m.created_at)} for m in rows]


@router.post("/helpdesk", status_code=201)
def helpdesk_post(body: HelpBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
    from app.services import notify
    bid = _help_branch(user, body.branch_id)
    text = (body.body or "").strip()
    if not text: raise ValidationFailed("Message is empty")
    db.add(Message(branch_id=bid, channel="helpdesk", author_id=user.id, body=text))
    if user.role in Role.BRANCH: notify.to_level(db, 1, f"Help desk message from {user.branch.name}", None, "helpdesk", True)
    else: notify.to_branch(db, bid, "Message from Head Office help desk", None, "helpdesk")
    db.commit()
    return {"ok": True}
