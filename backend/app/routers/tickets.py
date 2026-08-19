from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import (
    Ticket, Msg91Ticket, Customer, Consignment, TicketStatus, EscalationLevel,
    Priority, User
)
from app.schemas.schemas import (
    TicketListItem, ResolutionDetailsUpdate, CommentIn, EscalateIn, ResolveIn, ReassignIn
)
from app.services import escalation_service

router = APIRouter(prefix="/api/tickets", tags=["tickets"])


def _serialize(t: Ticket) -> TicketListItem:
    return TicketListItem(
        id=t.id,
        crm_code=t.crm_code,
        msg91_ticket_id=t.msg91_ticket.msg91_ticket_id,
        customer_name=t.msg91_ticket.customer_name,
        customer_number=t.msg91_ticket.customer_number,
        created_at=t.created_at,
        last_message_snippet=t.msg91_ticket.last_message_snippet,
        widget_unread_count=t.msg91_ticket.widget_unread_count or 0,
        assignee_type=t.msg91_ticket.assignee_type,
        status=t.status.value,
        escalation_level=t.escalation_level.value,
        priority=t.priority.value,
        assigned_user_name=t.assigned_user.name if t.assigned_user else None,
        updated_at=t.updated_at,
    )


@router.get("", response_model=list[TicketListItem])
def list_tickets(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    status_filter: Optional[str] = Query(None, alias="status"),
    escalation_level: Optional[str] = None,
    assigned_user_id: Optional[int] = None,
    priority: Optional[str] = None,
    search: Optional[str] = None,
    my_tickets: bool = False,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    page: int = 1,
    page_size: int = 25,
):
    q = db.query(Ticket).options(
        joinedload(Ticket.msg91_ticket), joinedload(Ticket.assigned_user)
    )

    if status_filter:
        q = q.filter(Ticket.status == status_filter)
    if escalation_level:
        q = q.filter(Ticket.escalation_level == escalation_level)
    if assigned_user_id:
        q = q.filter(Ticket.assigned_user_id == assigned_user_id)
    if priority:
        q = q.filter(Ticket.priority == priority)
    if my_tickets:
        q = q.filter(Ticket.assigned_user_id == user.id)

    if search:
        like = f"%{search}%"
        q = q.join(Msg91Ticket).filter(or_(
            Ticket.crm_code.ilike(like),
            Msg91Ticket.customer_name.ilike(like),
            Msg91Ticket.customer_number.ilike(like),
            Msg91Ticket.msg91_ticket_id.cast(str).ilike(like),
        ))

    sort_col = getattr(Ticket, sort_by, Ticket.created_at)
    q = q.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())

    q = q.offset((page - 1) * page_size).limit(page_size)
    return [_serialize(t) for t in q.all()]


def _get_ticket_or_404(db: Session, ticket_id: int) -> Ticket:
    t = db.query(Ticket).options(
        joinedload(Ticket.msg91_ticket), joinedload(Ticket.customer),
        joinedload(Ticket.consignment), joinedload(Ticket.comments),
        joinedload(Ticket.history),
    ).filter(Ticket.id == ticket_id).first()
    if not t:
        raise HTTPException(404, "Ticket not found")
    return t


@router.get("/{ticket_id}")
def get_ticket(ticket_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    t = _get_ticket_or_404(db, ticket_id)
    return {
        "id": t.id, "crm_code": t.crm_code, "status": t.status.value,
        "escalation_level": t.escalation_level.value, "priority": t.priority.value,
        "issue_summary": t.issue_summary, "comment_note": t.comment_note,
        "customer": {
            "name": t.customer.name if t.customer else None,
            "mobile": t.customer.mobile_number if t.customer else None,
        },
        "consignment": {
            "consignment_number": t.consignment.consignment_number,
            "address": t.consignment.address,
        } if t.consignment else None,
        "comments": [
            {"user": c.user.name, "level": c.escalation_level.value, "comment": c.comment,
             "created_at": c.created_at.isoformat()} for c in t.comments
        ],
        "history": [
            {"action": h.action, "prev_status": h.previous_status, "new_status": h.new_status,
             "user": h.user.name if h.user_id else "MSG91", "created_at": h.created_at.isoformat(),
             "comment": h.comment}
            for h in t.history
        ],
        "msg91_last_message": t.msg91_ticket.last_message_snippet,
        "msg91_ticket_id": t.msg91_ticket.msg91_ticket_id,
    }


@router.post("/{ticket_id}/pick", response_model=TicketListItem)
def pick_ticket(ticket_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    t = _get_ticket_or_404(db, ticket_id)
    escalation_service.pick_ticket(db, t, user)
    return _serialize(t)


@router.put("/{ticket_id}/details")
def update_details(ticket_id: int, payload: ResolutionDetailsUpdate,
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    t = _get_ticket_or_404(db, ticket_id)

    if payload.consignment_number:
        customer = t.customer
        consignment = db.query(Consignment).filter(
            Consignment.consignment_number == payload.consignment_number,
            Consignment.customer_id == customer.id,
        ).first()
        if not consignment:
            consignment = Consignment(
                consignment_number=payload.consignment_number,
                customer_id=customer.id,
                receiver_name=payload.customer_name,
                receiver_mobile=payload.mobile_number,
                address=payload.address,
            )
            db.add(consignment)
            db.flush()
        t.consignment_id = consignment.id

    if payload.issue_summary:
        t.issue_summary = payload.issue_summary
    if payload.comment_note:
        t.comment_note = payload.comment_note

    db.commit()
    return {"ok": True}


@router.post("/{ticket_id}/comments")
def add_comment(ticket_id: int, payload: CommentIn,
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    t = _get_ticket_or_404(db, ticket_id)
    escalation_service.add_comment(db, t, user, payload.comment)
    return {"ok": True}


@router.post("/{ticket_id}/escalate", response_model=TicketListItem)
def escalate_ticket(ticket_id: int, payload: EscalateIn,
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    t = _get_ticket_or_404(db, ticket_id)
    force_level = EscalationLevel(payload.force_level) if payload.force_level else None
    escalation_service.escalate(db, t, user, payload.reason, force_level=force_level)
    return _serialize(t)


@router.post("/{ticket_id}/resolve", response_model=TicketListItem)
def resolve_ticket(ticket_id: int, payload: ResolveIn,
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    t = _get_ticket_or_404(db, ticket_id)
    escalation_service.resolve(db, t, user, payload.resolution_note)
    return _serialize(t)


@router.post("/{ticket_id}/close", response_model=TicketListItem)
def close_ticket(ticket_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    t = _get_ticket_or_404(db, ticket_id)
    escalation_service.close(db, t, user)
    return _serialize(t)


@router.post("/{ticket_id}/reassign", response_model=TicketListItem)
def reassign_ticket(ticket_id: int, payload: ReassignIn,
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role.name.value != "admin":
        raise HTTPException(403, "Only Admin may reassign tickets")
    t = _get_ticket_or_404(db, ticket_id)
    new_user = db.query(User).get(payload.new_user_id)
    if not new_user:
        raise HTTPException(404, "Target user not found")
    escalation_service.reassign(db, t, user, new_user)
    return _serialize(t)


@router.post("/sync")
def trigger_sync(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Manual refresh/sync button (spec section 2). Admin/support can trigger."""
    from app.services.sync_service import sync_tickets
    result = sync_tickets(db)
    return result
