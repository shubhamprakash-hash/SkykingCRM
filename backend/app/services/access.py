"""Single place that decides who may see which complaint (branch scoping)."""
from sqlalchemy import or_, and_, exists, select
from sqlalchemy.orm import Session
from app.enums import Role, S
from app.models import Ticket, TicketBranch, Branch


def visible_filter(db: Session, user):
    """SQLAlchemy filter expression restricting Ticket rows to those `user` may see."""
    if user.role in Role.ADMIN:
        return Ticket.id.isnot(None)
    if user.role in Role.HO_LEVEL:
        return Ticket.status != S.DRAFT                      # drafts are visible to the branch only
    if user.role == Role.REGIONAL_MANAGER:
        ids = select(Branch.id).where(Branch.region_id == user.region_id)
        return and_(Ticket.status != S.DRAFT, or_(Ticket.branch_id.in_(ids), Ticket.origin_branch_id.in_(ids)))
    if user.role in Role.BRANCH and user.branch_id:
        hist = exists().where(and_(TicketBranch.ticket_id == Ticket.id, TicketBranch.branch_id == user.branch_id))
        return or_(Ticket.branch_id == user.branch_id, Ticket.origin_branch_id == user.branch_id, hist)
    return Ticket.id == -1                                    # no access


def visible_tickets(db: Session, user):
    return db.query(Ticket).filter(visible_filter(db, user))


def can_view(db: Session, user, ticket: Ticket) -> bool:
    return db.query(Ticket.id).filter(Ticket.id == ticket.id, visible_filter(db, user)).first() is not None


def branch_can_write(db: Session, user, t: Ticket) -> bool:
    """Branch users may update only while the ticket is currently assigned to / registered by their branch."""
    if user.role not in Role.BRANCH or not user.branch_id:
        return False
    return user.branch_id in (t.branch_id, t.origin_branch_id) and t.status not in (S.CLOSED,)
