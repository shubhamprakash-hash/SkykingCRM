from app.enums import Role, S
from app.models import Message, Attachment, TicketEvent, User, MessageRead
from app.services import workflow as wf, settings_service as cfgs
from app.services.calendar import working_minutes_between
from app.security import utcnow


def iso(d): return d.isoformat() + "Z" if d else None


def user_out(u: User):
    return {"id": u.id, "name": u.name, "email": u.email, "mobile": u.mobile, "role": u.role, "branch_id": u.branch_id,
            "branch": u.branch.name if u.branch else None, "status": u.status, "is_team_lead": u.is_team_lead,
            "last_login": iso(u.last_login)}


def ticket_out(db, t, user, detail=False):
    now = utcnow()
    d = {
        "id": t.id, "number": t.number, "source": t.source, "status": t.status, "level": t.level,
        "priority": t.priority, "urgent": t.urgent_flag, "subject": t.subject, "incomplete": t.incomplete,
        "customer": {"id": t.customer.id, "name": t.customer.name, "mobile": t.customer.mobile, "email": t.customer.email} if t.customer else None,
        "category": t.category.name if t.category else None, "category_id": t.category_id,
        "owner": t.owner.name if t.owner else None, "owner_id": t.owner_id,
        "branch": t.branch.name if t.branch else None, "branch_id": t.branch_id,
        "origin_branch": t.origin_branch.name if t.origin_branch else None, "origin_branch_id": t.origin_branch_id,
        "consignment_no": t.consignment_no, "pincode": t.pincode,
        "created_at": iso(t.created_at), "due_at": iso(t.due_at), "overdue": bool(t.due_at and t.due_at < now and t.status in S.OPEN),
        "age_hours": round((now - t.created_at).total_seconds() / 3600, 1),
        "cooling": t.cooling, "repeated_movement": t.repeated_movement, "version": t.version,
        "actions": wf.available_actions(db, t, user),
    }
    if t.due_at and t.status in S.OPEN | {S.RESOLVED}:
        d["minutes_left"] = int((t.due_at - now).total_seconds() // 60)
    if detail:
        d.update({
            "description": t.description, "receiver_name": t.receiver_name, "receiver_mobile": t.receiver_mobile,
            "address": t.address, "preferred_contact": t.preferred_contact, "preferred_language": t.preferred_language,
            "caller_number": t.caller_number, "call_received_at": iso(t.call_received_at), "call_reference": t.call_reference,
            "branch_deadline_minutes": t.branch_deadline_minutes, "extension_count": t.extension_count,
            "escalation_count": t.escalation_count, "deescalation_count": t.deescalation_count,
            "reopen_count": t.reopen_count, "branch_assignee_id": t.branch_assignee_id,
            "resolution": {"action": t.resolution_action, "outcome": t.resolution_outcome, "root_cause": t.root_cause,
                           "first_call": t.resolved_on_first_call, "resolved_at": iso(t.resolved_at)} if t.resolved_at else None,
            "forwarded_at": iso(t.forwarded_at), "merged_into_id": t.merged_into_id,
        })
        branchy = user.role in Role.BRANCH
        d["events"] = [{
            "id": e.id, "at": iso(e.at), "type": e.event_type, "actor": e.actor.name if e.actor else e.actor_type,
            "from_status": e.from_status, "to_status": e.to_status, "from_level": e.from_level, "to_level": e.to_level,
            "trigger": e.trigger, "reason_code": e.reason_code, "reason": e.reason, "note": e.note,
            "meta": None if branchy else e.meta,
        } for e in db.query(TicketEvent).filter_by(ticket_id=t.id).order_by(TicketEvent.id) if not (branchy and e.event_type in ("note",))]
        q = db.query(Message).filter(Message.ticket_id == t.id, Message.deleted.is_(False))
        if branchy: q = q.filter(Message.channel == "thread")
        msgs = q.order_by(Message.id).all()
        reads = {r.message_id for r in db.query(MessageRead).filter(MessageRead.user_id == user.id, MessageRead.message_id.in_([m.id for m in msgs] or [0]))}
        d["messages"] = [{"id": m.id, "channel": m.channel, "author": m.author.name if m.author else m.author_type,
                          "author_role": m.author.role if m.author else None, "author_type": m.author_type, "body": m.body,
                          "at": iso(m.created_at), "read": m.id in reads or m.author_id == user.id} for m in msgs]
        d["attachments"] = [{"id": a.id, "filename": a.filename, "size": a.size, "content_type": a.content_type}
                            for a in db.query(Attachment).filter_by(ticket_id=t.id)]
    return d
