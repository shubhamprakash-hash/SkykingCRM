"""
State machine per spec section 9. Escalation only moves one level at a time
unless the acting user is an Admin explicitly forcing a skip.
"""
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.models import (
    Ticket, TicketStatus, EscalationLevel, Escalation, TicketHistory,
    TicketComment, RoleName
)

# Legal single-step forward transitions
NEXT_LEVEL = {
    EscalationLevel.L0: EscalationLevel.L1,
    EscalationLevel.L1: EscalationLevel.L2,
    EscalationLevel.L2: EscalationLevel.L3,
}

STATUS_FOR_LEVEL = {
    EscalationLevel.L0: TicketStatus.UNDER_REVIEW,
    EscalationLevel.L1: TicketStatus.ESCALATED_L1,
    EscalationLevel.L2: TicketStatus.ESCALATED_L2,
    EscalationLevel.L3: TicketStatus.ESCALATED_L3,
}

# Which role is authorized to act at each level
ROLE_FOR_LEVEL = {
    EscalationLevel.L0: RoleName.SUPPORT,
    EscalationLevel.L1: RoleName.L1,
    EscalationLevel.L2: RoleName.L2,
    EscalationLevel.L3: RoleName.L3,
}


def assert_can_act(ticket: Ticket, user_role: RoleName):
    if user_role == RoleName.ADMIN:
        return
    expected_role = ROLE_FOR_LEVEL[ticket.escalation_level]
    if user_role != expected_role:
        raise HTTPException(403, f"Ticket is at {ticket.escalation_level.value}; "
                                  f"only {expected_role.value} or admin may act on it")


# Statuses that represent an unclaimed ticket sitting in some queue --
# L0's "Available" queue, or the L1/L2/L3 queue it just landed in after an
# escalation. Picking from any of these is a "claim", not a level change.
PICKABLE_STATUSES = {
    TicketStatus.AVAILABLE,
    TicketStatus.ESCALATED_L1,
    TicketStatus.ESCALATED_L2,
    TicketStatus.ESCALATED_L3,
}


def pick_ticket(db: Session, ticket: Ticket, user):
    if ticket.status not in PICKABLE_STATUSES:
        raise HTTPException(409, "Ticket is not currently available to pick")
    if ticket.assigned_user_id is not None:
        raise HTTPException(409, "Ticket already picked by another user")

    assert_can_act(ticket, user.role.name)

    prev_status = ticket.status
    # L0's pick moves status to PICKED; L1/L2/L3 picks keep the
    # escalated_* status (it just gains an owner) so it's clear which
    # level is currently working it.
    new_status = TicketStatus.PICKED if ticket.escalation_level == EscalationLevel.L0 else ticket.status
    ticket.status = new_status
    ticket.assigned_user_id = user.id
    db.add(TicketHistory(
        ticket_id=ticket.id, action="picked",
        previous_status=prev_status.value, new_status=new_status.value,
        previous_assignee_id=None, new_assignee_id=user.id,
        user_id=user.id, escalation_level=ticket.escalation_level.value,
    ))
    db.commit()
    return ticket


def add_comment(db: Session, ticket: Ticket, user, comment: str):
    db.add(TicketComment(
        ticket_id=ticket.id, user_id=user.id,
        escalation_level=ticket.escalation_level, comment=comment,
    ))
    db.add(TicketHistory(
        ticket_id=ticket.id, action="comment_added",
        previous_status=ticket.status.value, new_status=ticket.status.value,
        user_id=user.id, escalation_level=ticket.escalation_level.value,
        comment=comment,
    ))
    db.commit()


def escalate(db: Session, ticket: Ticket, user, reason: str, force_level: EscalationLevel = None):
    assert_can_act(ticket, user.role.name)

    forced = force_level is not None
    if forced and user.role.name != RoleName.ADMIN:
        raise HTTPException(403, "Only Admin may skip escalation levels")

    target_level = force_level or NEXT_LEVEL.get(ticket.escalation_level)
    if target_level is None:
        raise HTTPException(400, "Ticket is already at the highest escalation level (L3)")

    prev_level = ticket.escalation_level
    prev_status = ticket.status
    prev_assignee = ticket.assigned_user_id

    db.add(Escalation(
        ticket_id=ticket.id, from_level=prev_level, to_level=target_level,
        from_user_id=user.id, to_user_id=None, reason=reason, forced_by_admin=forced,
    ))

    ticket.escalation_level = target_level
    ticket.status = STATUS_FOR_LEVEL[target_level]
    ticket.assigned_user_id = None  # goes back into that level's queue, unclaimed

    db.add(TicketHistory(
        ticket_id=ticket.id, action=f"escalated_to_{target_level.value}",
        previous_status=prev_status.value, new_status=ticket.status.value,
        previous_assignee_id=prev_assignee, new_assignee_id=None,
        user_id=user.id, escalation_level=target_level.value, comment=reason,
    ))
    db.commit()
    return ticket


def resolve(db: Session, ticket: Ticket, user, resolution_note: str):
    assert_can_act(ticket, user.role.name)
    from datetime import datetime
    prev_status = ticket.status
    ticket.status = TicketStatus.RESOLVED
    ticket.resolved_at = datetime.utcnow()
    if resolution_note:
        ticket.comment_note = resolution_note
    db.add(TicketHistory(
        ticket_id=ticket.id, action="resolved",
        previous_status=prev_status.value, new_status=TicketStatus.RESOLVED.value,
        user_id=user.id, escalation_level=ticket.escalation_level.value, comment=resolution_note,
    ))
    db.commit()
    return ticket


def close(db: Session, ticket: Ticket, user):
    if user.role.name not in (RoleName.L3, RoleName.ADMIN):
        raise HTTPException(403, "Only L3 or Admin may close a ticket")
    if ticket.status != TicketStatus.RESOLVED:
        raise HTTPException(409, "Only resolved tickets can be closed")
    from datetime import datetime
    prev_status = ticket.status
    ticket.status = TicketStatus.CLOSED
    ticket.closed_at = datetime.utcnow()
    db.add(TicketHistory(
        ticket_id=ticket.id, action="closed",
        previous_status=prev_status.value, new_status=TicketStatus.CLOSED.value,
        user_id=user.id, escalation_level=ticket.escalation_level.value,
    ))
    db.commit()
    return ticket


def reassign(db: Session, ticket: Ticket, admin_user, new_user):
    """Admin-only: reassign a ticket to a different user."""
    prev_assignee = ticket.assigned_user_id
    ticket.assigned_user_id = new_user.id
    db.add(TicketHistory(
        ticket_id=ticket.id, action="reassigned",
        previous_status=ticket.status.value, new_status=ticket.status.value,
        previous_assignee_id=prev_assignee, new_assignee_id=new_user.id,
        user_id=admin_user.id, escalation_level=ticket.escalation_level.value,
    ))
    db.commit()
    return ticket
