import logging
from sqlalchemy.orm import Session
from app.models import Notification, OutboundMessage, User, Ticket
from app.enums import Role

log = logging.getLogger("skyking.notify")


def to_users(db: Session, user_ids, text: str, ticket: Ticket | None = None, kind: str = "info"):
    for uid in {u for u in user_ids if u}:
        db.add(Notification(user_id=uid, ticket_id=ticket.id if ticket else None, kind=kind, text=text))


def to_level(db: Session, level: int, text: str, ticket=None, kind="info", team_leads_only=False):
    q = db.query(User.id).filter(User.role == f"L{level}", User.status == "active")
    if team_leads_only:
        q = q.filter(User.is_team_lead.is_(True))
    to_users(db, [r[0] for r in q], text, ticket, kind)


def to_admins(db: Session, text: str, ticket=None, kind="alert"):
    to_users(db, [r[0] for r in db.query(User.id).filter(User.role.in_(Role.ADMIN), User.status == "active")],
             text, ticket, kind)


def to_branch(db: Session, branch_id: int | None, text: str, ticket=None, kind="info", admins_only=False):
    if not branch_id:
        return
    q = db.query(User.id).filter(User.branch_id == branch_id, User.status == "active")
    if admins_only:
        q = q.filter(User.role == Role.BRANCH_ADMIN)
    to_users(db, [r[0] for r in q], text, ticket, kind)


def to_customer(db: Session, ticket: Ticket, body: str):
    """Queue a customer message (acknowledgement, confirmation request...) on the best channel."""
    c = ticket.customer
    if not c:
        return
    if c.mobile:
        chan, to = ("whatsapp" if ticket.source == "whatsapp" else "sms"), c.mobile
    elif c.email:
        chan, to = "email", c.email
    else:
        return
    db.add(OutboundMessage(ticket_id=ticket.id, channel=chan, to=to, body=body))
