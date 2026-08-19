from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import Ticket, TicketStatus, EscalationLevel, Priority, User

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _count(db: Session, **filters):
    q = db.query(func.count(Ticket.id))
    for k, v in filters.items():
        q = q.filter(getattr(Ticket, k) == v)
    return q.scalar()


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    base = {
        "total_tickets": db.query(func.count(Ticket.id)).scalar(),
        "available_tickets": _count(db, status=TicketStatus.AVAILABLE),
        "l1_tickets": _count(db, status=TicketStatus.ESCALATED_L1),
        "l2_tickets": _count(db, status=TicketStatus.ESCALATED_L2),
        "l3_tickets": _count(db, status=TicketStatus.ESCALATED_L3),
        "resolved_today": db.query(func.count(Ticket.id)).filter(
            Ticket.status == TicketStatus.RESOLVED, Ticket.resolved_at >= today_start
        ).scalar(),
        "pending_tickets": db.query(func.count(Ticket.id)).filter(
            Ticket.status.notin_([TicketStatus.RESOLVED, TicketStatus.CLOSED])
        ).scalar(),
        "critical_tickets": _count(db, priority=Priority.CRITICAL),
    }

    role = user.role.name.value
    if role == "admin":
        return base

    if role == "support":
        return {
            "available_tickets": base["available_tickets"],
            "my_tickets": db.query(func.count(Ticket.id)).filter(
                Ticket.assigned_user_id == user.id,
                Ticket.status.notin_([TicketStatus.RESOLVED, TicketStatus.CLOSED]),
            ).scalar(),
            "pending_tickets": base["pending_tickets"],
            "escalated_tickets": db.query(func.count(Ticket.id)).filter(
                Ticket.escalation_level != EscalationLevel.L0
            ).scalar(),
            "resolved_tickets": db.query(func.count(Ticket.id)).filter(
                Ticket.status == TicketStatus.RESOLVED
            ).scalar(),
        }

    level_map = {"l1": TicketStatus.ESCALATED_L1, "l2": TicketStatus.ESCALATED_L2, "l3": TicketStatus.ESCALATED_L3}
    if role in level_map:
        return {
            "waiting_at_level": _count(db, status=level_map[role]),
            "my_tickets": db.query(func.count(Ticket.id)).filter(
                Ticket.assigned_user_id == user.id,
                Ticket.status == level_map[role],
            ).scalar(),
            "resolved_tickets": base["resolved_today"],
        }

    return base
