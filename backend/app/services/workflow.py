"""
The complaint state machine.

Every status change goes through `_transition`, which (1) validates the move against ALLOWED,
(2) updates the ticket, (3) re-arms the timer and (4) appends the audit event - all in the
caller's single database transaction. Nothing else in the code base assigns `ticket.status`.
"""
import re
from datetime import timedelta
from sqlalchemy.orm import Session
from app.enums import Role, S, PRIORITIES, SOURCES, DEESCALATION_REASONS
from app.models import (Ticket, TicketEvent, Customer, Counter, User, Branch, TicketBranch, Message,
                        Category)
from app.security import utcnow
from app.services import settings_service as cfgs, notify
from app.services.calendar import add_working_minutes, working_minutes_between
from app.services.access import branch_can_write
from app.services.errors import (NotAllowed, InvalidTransition, ValidationFailed, DuplicateFound,
                                 NotFound, Conflict)

KEEP = object()

# ---------------------------------------------------------------------------------------------
# The complete list of permitted status moves (Section 5.9 of the blueprint).
# ---------------------------------------------------------------------------------------------
_OPEN = set(S.OPEN)
ALLOWED = {
    S.DRAFT: {S.L1_QUEUE},
    S.L1_QUEUE: {S.L1_WORKING, S.L2_QUEUE, S.RESOLVED, S.AWAITING_CUSTOMER, S.AWAITING_BRANCH_INFO, S.DRAFT},
    S.L1_WORKING: {S.L1_QUEUE, S.L2_QUEUE, S.RESOLVED, S.AWAITING_CUSTOMER, S.AWAITING_BRANCH_INFO},
    S.L2_QUEUE: {S.L2_WORKING, S.L3_QUEUE, S.L1_QUEUE, S.L1_WORKING, S.ASSIGNED_BRANCH, S.RESOLVED,
                 S.AWAITING_CUSTOMER},
    S.L2_WORKING: {S.L2_QUEUE, S.L3_QUEUE, S.L1_QUEUE, S.L1_WORKING, S.ASSIGNED_BRANCH, S.RESOLVED,
                   S.AWAITING_CUSTOMER},
    S.ASSIGNED_BRANCH: {S.ASSIGNED_BRANCH, S.BRANCH_ACK, S.ACTION_TAKEN, S.L3_QUEUE, S.L2_QUEUE, S.L1_QUEUE,
                        S.L1_WORKING, S.RESOLVED, S.AWAITING_CUSTOMER},
    S.BRANCH_ACK: {S.ASSIGNED_BRANCH, S.ACTION_TAKEN, S.L3_QUEUE, S.L2_QUEUE, S.L1_QUEUE, S.L1_WORKING,
                   S.RESOLVED, S.AWAITING_CUSTOMER},
    S.ACTION_TAKEN: {S.RESOLVED, S.ASSIGNED_BRANCH, S.L3_QUEUE, S.L1_QUEUE, S.L1_WORKING},
    S.L3_QUEUE: {S.L3_WORKING, S.L2_QUEUE, S.L2_WORKING, S.RESOLVED, S.AWAITING_CUSTOMER},
    S.L3_WORKING: {S.L3_QUEUE, S.L2_QUEUE, S.L2_WORKING, S.RESOLVED, S.AWAITING_CUSTOMER},
    S.AWAITING_CUSTOMER: _OPEN - {S.AWAITING_CUSTOMER, S.AWAITING_BRANCH_INFO} | {S.RESOLVED},
    S.AWAITING_BRANCH_INFO: {S.L1_QUEUE, S.L1_WORKING, S.RESOLVED},
    S.RESOLVED: {S.CLOSED, S.L1_QUEUE, S.L2_QUEUE, S.L3_QUEUE},
    S.CLOSED: {S.L1_QUEUE, S.L2_QUEUE, S.L3_QUEUE},
}
CREATE_STATES = {S.DRAFT, S.L1_QUEUE, S.L2_QUEUE, S.L3_QUEUE}
# Only these two exceptional channels may bypass ALLOWED; both are explicit and audited.
VIA_RULES = {
    "merge": lambda old, new: old in (_OPEN | {S.RESOLVED}) and new == S.CLOSED,
    "admin_force": lambda old, new: True,
}


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------
def _now(now): return now or utcnow()
def is_admin(u): return bool(u) and u.role in Role.ADMIN
def user_level(u): return Role.LEVEL_OF.get(u.role) if u else None
def is_branch(u): return bool(u) and u.role in Role.BRANCH
def is_ho(u): return bool(u) and (u.role in Role.HO_LEVEL or u.role in Role.ADMIN)
def at_level(u, t): return is_admin(u) or (user_level(u) is not None and user_level(u) == t.level)


def norm_mobile(m):
    if not m: return None
    d = re.sub(r"\D", "", str(m))
    if len(d) == 12 and d.startswith("91"): d = d[2:]
    if len(d) == 11 and d.startswith("0"): d = d[1:]
    return d or None


def next_number(db: Session) -> str:
    c = db.get(Counter, "ticket", with_for_update=True)
    if c is None:
        c = Counter(name="ticket", value=0); db.add(c); db.flush()
    c.value += 1
    db.flush()
    return f"CRM-{c.value:07d}"


def acts_on_clock(u, t) -> bool:
    """Whose actions count as 'attending' the complaint for the current timer."""
    if t.status in (S.ASSIGNED_BRANCH, S.BRANCH_ACK):
        return is_branch(u) and u.branch_id == t.branch_id
    if is_admin(u): return True
    return user_level(u) == t.level


def _is_timed(status): return status in S.LEVEL_OF or status in (S.AWAITING_BRANCH_INFO, S.RESOLVED)


def arm(db, t, now, minutes=None):
    """(Re)start the clock that applies to the ticket's current status."""
    s, c = t.status, cfgs.cfg(db)
    cal = cfgs.calendar(db)
    if s in S.LEVEL_OF and s not in (S.ASSIGNED_BRANCH, S.BRANCH_ACK):
        m = minutes if minutes is not None else cfgs.threshold(db, S.LEVEL_OF[s], t.priority)
        t.due_at = add_working_minutes(now, m, cal)
    elif s in (S.ASSIGNED_BRANCH, S.BRANCH_ACK):
        m = minutes if minutes is not None else (t.branch_deadline_minutes or c["branch_deadline_default"])
        t.due_at = add_working_minutes(now, m, cal)
    elif s == S.AWAITING_BRANCH_INFO:
        t.due_at = add_working_minutes(now, minutes if minutes is not None else c["info_limit_minutes"], cal)
    elif s == S.RESOLVED:
        t.due_at = now + timedelta(hours=c["auto_close_hours"])
    else:
        t.due_at = None
    t.warned_at = None
    t.last_activity_at = now


def log(db, t, etype, actor=None, *, frm=(None, None), to=None, trigger=None, reason_code=None,
        reason=None, note=None, meta=None, now=None, actor_type=None):
    ev = TicketEvent(ticket_id=t.id, at=_now(now), actor_id=actor.id if actor else None,
                     actor_type=actor_type or ("user" if actor else "system"), event_type=etype,
                     from_status=frm[0], to_status=(to[0] if to else t.status),
                     from_level=frm[1], to_level=(to[1] if to else t.level), trigger=trigger,
                     reason_code=reason_code, reason=reason, note=note, meta=meta)
    db.add(ev)
    return ev


def _move(db, t, new, now, *, level=None, via=None):
    old = t.status
    if via:
        if not VIA_RULES[via](old, new):
            raise InvalidTransition(f"{via} cannot move {old} -> {new}")
    elif old is None:
        if new not in CREATE_STATES:
            raise InvalidTransition(f"cannot create a complaint directly in {new}")
    elif new not in ALLOWED.get(old, set()):
        raise InvalidTransition(f"Move {old} -> {new} is not allowed", from_status=old, to_status=new)
    lvl = S.LEVEL_OF.get(new)
    if lvl is not None and level is not None and level != lvl:
        raise InvalidTransition(f"{new} belongs to level {lvl}, not {level}")
    new_level = lvl if lvl is not None else (None if new == S.DRAFT else (level or t.level))
    old_level = t.level
    t.status, t.level = new, new_level
    if new_level != old_level:
        t.level_entered_at = now
        if old_level is not None and new_level is not None:
            t.moves_count = (t.moves_count or 0) + 1
    return (old, old_level)


def _transition(db, t, actor, etype, new, now, *, level=None, owner=KEEP, trigger="manual", reason_code=None,
                reason=None, note=None, meta=None, rearm=True, via=None, actor_type=None, minutes=None):
    prev = _move(db, t, new, now, level=level, via=via)
    if owner is not KEEP:
        t.owner_id = owner
    if rearm:
        arm(db, t, now, minutes)
    if t.id is None:
        db.flush()
    ev = log(db, t, etype, actor, frm=prev, trigger=trigger, reason_code=reason_code, reason=reason,
             note=note, meta=meta, now=now, actor_type=actor_type)
    c = cfgs.cfg(db)
    if (t.moves_count or 0) >= c["repeated_movement_at"] and not t.repeated_movement:
        t.repeated_movement = True
        notify.to_admins(db, f"{t.number}: repeated movement between levels", t, "alert")
        notify.to_level(db, t.level or 1, f"{t.number}: repeated movement between levels", t, "alert", True)
    db.flush()
    return ev


def _touch(db, t, actor, now):
    """A logged action by someone attending the complaint: resets the timer, ends the cooling period."""
    if not actor or not acts_on_clock(actor, t):
        return
    if t.cooling and user_level(actor) == t.level:
        t.cooling = False
    if _is_timed(t.status) and t.status != S.RESOLVED:
        if t.status != S.AWAITING_BRANCH_INFO:
            arm(db, t, now)


def _text(v, name, minlen=1):
    v = (v or "").strip()
    if len(v) < minlen:
        raise ValidationFailed(f"{name} is required (at least {minlen} characters)")
    return v


def _set_owner_memory(t, level, uid):
    m = dict(t.prev_owner_by_level or {}); m[str(level)] = uid; t.prev_owner_by_level = m


# ---------------------------------------------------------------------------------------------
# creation
# ---------------------------------------------------------------------------------------------
def find_customer(db, mobile=None, email=None):
    m = norm_mobile(mobile)
    if m:
        c = db.query(Customer).filter(Customer.mobile == m).first()
        if c: return c
    if email:
        return db.query(Customer).filter(Customer.email == email.strip().lower()).first()
    return None


def find_duplicates(db, customer, consignment_no):
    if not customer or not consignment_no:
        return []
    return db.query(Ticket).filter(Ticket.customer_id == customer.id, Ticket.consignment_no == consignment_no,
                                   Ticket.status.in_(list(S.OPEN))).all()


DETAIL_FIELDS = ["consignment_no", "receiver_name", "receiver_mobile", "address", "pincode",
                 "preferred_contact", "preferred_language", "caller_number", "call_reference", "subject",
                 "category_id"]


def _is_incomplete(t): return not (t.consignment_no and t.pincode)


def create_ticket(db: Session, creator, *, source, description, mobile=None, email=None, name=None,
                  category_id=None, subject=None, priority=None, urgent=False, mode="queue", level=None,
                  allow_duplicate=False, resolve=None, now=None, **details):
    """
    mode: 'queue' (L1 queue) | 'take' (assign to me) | 'draft' (branch only) .
    Branch creators default to register-and-forward (L1 queue) unless mode == 'draft'.
    `creator=None` means a system intake channel (WhatsApp / email).
    """
    now = _now(now)
    if source not in SOURCES: raise ValidationFailed(f"unknown source {source}")
    description = _text(description, "Description", 3)
    if creator and is_branch(creator):
        if creator.role not in Role.BRANCH or not creator.branch_id: raise NotAllowed("Branch user has no branch")
        br = db.get(Branch, creator.branch_id)
        if br.status != "live": raise NotAllowed("Your branch is not live yet")
        source = "branch"
    elif creator and not is_ho(creator):
        raise NotAllowed("This role cannot create complaints")
    if creator and mode != "draft":
        if not norm_mobile(mobile) and not email: raise ValidationFailed("Customer mobile (or email) is required")
        if not category_id: raise ValidationFailed("Category is required")
    if category_id and not db.get(Category, category_id): raise ValidationFailed("Unknown category")
    if not (norm_mobile(mobile) or email) and mode != "draft" and creator is not None:
        raise ValidationFailed("Customer mobile is required")

    customer = find_customer(db, mobile, email)
    if customer is None and (norm_mobile(mobile) or email):
        customer = Customer(name=name, mobile=norm_mobile(mobile), email=(email or "").strip().lower() or None)
        db.add(customer); db.flush()
    elif customer is not None and name and not customer.name:
        customer.name = name
    dups = find_duplicates(db, customer, details.get("consignment_no"))
    if dups and not allow_duplicate:
        raise DuplicateFound("An open complaint already exists for this customer and consignment",
                             ticket_ids=[d.id for d in dups], numbers=[d.number for d in dups])

    cat = db.get(Category, category_id) if category_id else None
    pr = priority or (cat.default_priority if cat else "medium")
    if pr not in PRIORITIES: raise ValidationFailed("invalid priority")
    if urgent and PRIORITIES.index(pr) < PRIORITIES.index("high"): pr = "high"

    t = Ticket(number=next_number(db), source=source, customer_id=customer.id if customer else None,
               category_id=category_id, subject=(subject or description[:80]), description=description,
               priority=pr, urgent_flag=bool(urgent), created_by=creator.id if creator else None,
               registered_by=creator.id if creator else None, created_at=now, version=1, status=None)
    for k in DETAIL_FIELDS:
        if k in details and details[k] not in (None, ""): setattr(t, k, details[k])
    if "category_id" not in details: t.category_id = category_id
    if t.receiver_mobile: t.receiver_mobile = norm_mobile(t.receiver_mobile)
    t.caller_number = norm_mobile(t.caller_number)
    t.call_received_at = details.get("call_received_at")
    t.incomplete = _is_incomplete(t)
    t.prev_owner_by_level = {}
    if creator and is_branch(creator): t.origin_branch_id = creator.branch_id
    db.add(t)

    if creator and is_branch(creator):
        target, lvl = (S.DRAFT, None) if mode == "draft" else (S.L1_QUEUE, 1)
    else:
        lvl = level or 1
        if creator and not is_admin(creator) and level and level != user_level(creator):
            raise NotAllowed("You can only create a complaint at your own level")
        if creator and not is_admin(creator) and not level: lvl = user_level(creator) or 1
        target = S.QUEUE[lvl]
    _transition(db, t, creator, "created", target, now, level=lvl, trigger="system" if not creator else "manual",
                meta={"source": source, "mode": mode, "incomplete": t.incomplete},
                actor_type=None if creator else "system", rearm=(target != S.DRAFT))
    if target == S.L1_QUEUE and creator and is_branch(creator):
        t.forwarded_at = now
        log(db, t, "forwarded", creator, to=(t.status, t.level), now=now, note="Registered and forwarded to Head Office")
    if target != S.DRAFT:
        notify.to_customer(db, t, f"We have registered your complaint {t.number}. We will update you shortly.")
        if t.urgent_flag:
            notify.to_level(db, 1, f"URGENT: {t.number} registered by a branch", t, "alert", True)
            notify.to_level(db, 2, f"URGENT: {t.number} registered by a branch", t, "alert", True)
    if mode == "take" and creator and not is_branch(creator) and target != S.DRAFT:
        pick(db, t, creator, now=now)
    if resolve:
        resolve_ticket(db, t, creator, now=now, first_call=True, **resolve)
    return t


# ---------------------------------------------------------------------------------------------
# actions: each has a `pre_*` (state + permission check, no parameters) and the action itself.
# ---------------------------------------------------------------------------------------------
def _req(cond, msg="Not allowed"):
    if not cond: raise NotAllowed(msg)


def pre_pick(db, t, u):
    _req(t.status in S.QUEUE.values() and t.owner_id is None, "Complaint is not waiting in a queue")
    _req(not is_branch(u) and at_level(u, t), "Only the owning level can pick this complaint")


def pick(db, t, u, now=None):
    now = _now(now); pre_pick(db, t, u)
    lvl = t.level
    _transition(db, t, u, "picked", S.WORKING[lvl], now, owner=u.id)
    _set_owner_memory(t, lvl, u.id)
    _touch(db, t, u, now)
    return t


def pre_release(db, t, u):
    _req(t.status in S.WORKING.values(), "Complaint is not being worked")
    _req(t.owner_id == u.id or is_admin(u) or (u.is_team_lead and user_level(u) == t.level), "Only the owner can release")


def release(db, t, u, now=None):
    now = _now(now); pre_release(db, t, u)
    _transition(db, t, u, "released", S.QUEUE[t.level], now, owner=None)
    return t


def pre_escalate(db, t, u):
    _req(not is_branch(u) and t.level in (1, 2), "Only L1 and L2 can escalate")
    _req(t.status in (S.QUEUE.get(t.level), S.WORKING.get(t.level)) or t.status in S.BRANCH_PHASE,
         "Complaint cannot be escalated from this status")
    _req(is_admin(u) or user_level(u) == t.level, "Only the current level can escalate")
    _req(not t.cooling or is_admin(u),
         "This complaint was just sent back: log an action before escalating it again")


def escalate(db, t, u, reason, now=None):
    now = _now(now); pre_escalate(db, t, u)
    reason = _text(reason, "Reason", 3)
    frm = t.level
    _transition(db, t, u, "escalated", S.QUEUE[frm + 1], now, owner=None,
                trigger="l2_direct" if frm == 2 else "manual", reason=reason)
    t.escalation_count = (t.escalation_count or 0) + 1
    t.cooling = False
    notify.to_level(db, frm + 1, f"{t.number} escalated to L{frm + 1}: {reason}", t, "escalation")
    return t


def pre_deescalate(db, t, u):
    _req(not is_branch(u) and t.level in (2, 3), "Only L2 and L3 can send a complaint back")
    _req(t.status in (S.OPEN - S.PAUSED), "This complaint cannot be sent back in its current status")
    _req(is_admin(u) or user_level(u) == t.level, "Only the current level can send it back")


def deescalate(db, t, u, reason_code, note, target_user_id=None, withdraw_branch=None, skip=False, now=None):
    now = _now(now); pre_deescalate(db, t, u)
    c = cfgs.cfg(db)
    if reason_code not in DEESCALATION_REASONS: raise ValidationFailed("Choose a valid reason")
    note = _text(note, "Handover note", c["min_handover_chars"])
    if skip and not (is_admin(u) and t.level == 3): raise NotAllowed("Only Admin can skip a level")
    if (t.deescalation_count or 0) >= c["max_deescalations"] and not is_admin(u):
        raise NotAllowed("Send-back limit reached: Admin approval is needed")
    frm = t.level
    target = 1 if skip else frm - 1
    had_branch = t.branch_id is not None
    if frm == 2 and had_branch:
        if withdraw_branch is None:
            raise ValidationFailed("Choose whether to withdraw the branch assignment or keep it")
        if withdraw_branch:
            _withdraw_branch(db, t, now)
    owner, new_status = None, S.QUEUE[target]
    if target_user_id:
        tu = db.get(User, target_user_id)
        if not tu or tu.status != "active" or user_level(tu) != target:
            raise ValidationFailed(f"Choose an active L{target} user")
        owner, new_status = tu.id, S.WORKING[target]
    elif not skip:
        pu = db.get(User, (t.prev_owner_by_level or {}).get(str(target)) or 0)
        if pu and pu.status == "active" and user_level(pu) == target:
            owner, new_status = pu.id, S.WORKING[target]
    _transition(db, t, u, "deescalated", new_status, now, owner=owner, trigger="deescalate",
                reason_code=reason_code, note=note, meta={"skip": skip, "branch_withdrawn": bool(withdraw_branch)},
                via="admin_force" if skip else None)
    t.deescalation_count = (t.deescalation_count or 0) + 1
    t.cooling = True
    if owner: _set_owner_memory(t, target, owner)
    msg = f"{t.number} sent back to L{target} from L{frm}: {note[:120]}"
    notify.to_level(db, target, msg, t, "deescalation", team_leads_only=True)
    notify.to_users(db, [owner], msg, t, "deescalation")
    return t


def _withdraw_branch(db, t, now):
    for tb in db.query(TicketBranch).filter_by(ticket_id=t.id, branch_id=t.branch_id):
        tb.active = False
    notify.to_branch(db, t.branch_id, f"{t.number}: assignment withdrawn by Head Office (thread is now read-only)", t)
    t.branch_id = None
    t.branch_assignee_id = None


def pre_assign_branch(db, t, u):
    _req(not is_branch(u) and (is_admin(u) or user_level(u) == 2), "Only L2 can assign to a branch")
    _req(t.level == 2 and t.status in (S.L2_QUEUE, S.L2_WORKING, S.ASSIGNED_BRANCH, S.BRANCH_ACK),
         "Complaint is not at L2")


def assign_branch(db, t, u, branch_id, deadline_minutes=None, assignee_id=None, now=None):
    now = _now(now); pre_assign_branch(db, t, u)
    c = cfgs.cfg(db)
    br = db.get(Branch, branch_id)
    if not br: raise NotFound("Branch not found")
    if br.status != "live": raise ValidationFailed("Branch is not live")
    if _is_incomplete(t): raise ValidationFailed("Complete the consignment number and pincode before assigning to a branch")
    dl = deadline_minutes or c["branch_deadline_default"]
    if not (c["branch_deadline_min"] <= dl <= c["branch_deadline_max"]):
        raise ValidationFailed(f"Deadline must be between {c['branch_deadline_min']} and {c['branch_deadline_max']} minutes")
    if assignee_id:
        au = db.get(User, assignee_id)
        if not au or au.branch_id != branch_id or au.status != "active": raise ValidationFailed("Invalid branch assignee")
    old_branch = t.branch_id
    if old_branch and old_branch != branch_id:
        for tb in db.query(TicketBranch).filter_by(ticket_id=t.id, branch_id=old_branch): tb.active = False
    t.branch_id, t.branch_assignee_id, t.branch_deadline_minutes, t.extension_count = branch_id, assignee_id, dl, 0
    if not db.query(TicketBranch).filter_by(ticket_id=t.id, branch_id=branch_id).first():
        db.add(TicketBranch(ticket_id=t.id, branch_id=branch_id))
    else:
        db.query(TicketBranch).filter_by(ticket_id=t.id, branch_id=branch_id).update({"active": True})
    owner = t.owner_id or (u.id if user_level(u) == 2 else None)
    _transition(db, t, u, "assigned_branch", S.ASSIGNED_BRANCH, now, owner=owner,
                meta={"branch": br.code, "deadline_minutes": dl, "reassigned_from": old_branch})
    t.cooling = False
    notify.to_branch(db, branch_id, f"{t.number} assigned to {br.name}. Deadline: {dl // 60}h {dl % 60}m", t, "assignment")
    if old_branch and old_branch != branch_id:
        notify.to_branch(db, old_branch, f"{t.number} was moved to another branch", t)
    return t


def pre_extend(db, t, u, now=None):
    _req(not is_branch(u) and (is_admin(u) or user_level(u) == 2), "Only L2 can extend a branch deadline")
    _req(t.status in (S.ASSIGNED_BRANCH, S.BRANCH_ACK) and t.due_at is not None, "No branch deadline to extend")
    _req(t.due_at > _now(now), "The deadline has already passed")


def extend_deadline(db, t, u, minutes, reason, now=None):
    now = _now(now); pre_extend(db, t, u, now)
    c = cfgs.cfg(db)
    if (t.extension_count or 0) >= c["max_extensions"]:
        raise ValidationFailed("Extension limit reached for this complaint")
    if not (30 <= int(minutes) <= 1440): raise ValidationFailed("Extension must be 30 to 1440 minutes")
    reason = _text(reason, "Reason", 3)
    before = t.due_at
    t.due_at = add_working_minutes(before, int(minutes), cfgs.calendar(db))
    t.warned_at = None
    t.extension_count = (t.extension_count or 0) + 1
    log(db, t, "deadline_extended", u, frm=(t.status, t.level), reason=reason, now=now,
        meta={"minutes": int(minutes), "from": before.isoformat(), "to": t.due_at.isoformat()})
    notify.to_branch(db, t.branch_id, f"{t.number}: deadline extended", t)
    return t


def _branch_user_ok(u, t): return is_branch(u) and u.branch_id == t.branch_id and t.branch_id is not None


def pre_branch_ack(db, t, u):
    _req(_branch_user_ok(u, t) and t.status == S.ASSIGNED_BRANCH, "Nothing to acknowledge")


def branch_ack(db, t, u, now=None):
    now = _now(now); pre_branch_ack(db, t, u)
    _transition(db, t, u, "branch_acknowledged", S.BRANCH_ACK, now)
    notify.to_users(db, [t.owner_id], f"{t.number} acknowledged by branch", t)
    return t


def pre_branch_action(db, t, u):
    _req(_branch_user_ok(u, t) and t.status in (S.ASSIGNED_BRANCH, S.BRANCH_ACK), "Nothing to update")


def branch_action_taken(db, t, u, notes, now=None):
    now = _now(now); pre_branch_action(db, t, u)
    notes = _text(notes, "Action taken", 10)
    _transition(db, t, u, "action_taken", S.ACTION_TAKEN, now, note=notes)
    if t.owner_id: notify.to_users(db, [t.owner_id], f"{t.number}: branch reports action taken - please verify", t, "verify")
    else: notify.to_level(db, 2, f"{t.number}: branch reports action taken - please verify", t, "verify")
    return t


def pre_branch_return(db, t, u):
    _req(_branch_user_ok(u, t) and t.status in (S.ASSIGNED_BRANCH, S.BRANCH_ACK), "Nothing to return")


def branch_return(db, t, u, reason, now=None):
    now = _now(now); pre_branch_return(db, t, u)
    reason = _text(reason, "Reason", 5)
    _withdraw_branch_quiet(db, t)
    _transition(db, t, u, "branch_return", S.L2_QUEUE, now, owner=None, trigger="branch_return", reason=reason)
    notify.to_level(db, 2, f"{t.number} returned by branch: {reason}", t, "branch_return")
    return t


def _withdraw_branch_quiet(db, t):
    for tb in db.query(TicketBranch).filter_by(ticket_id=t.id, branch_id=t.branch_id): tb.active = False
    t.branch_id = None
    t.branch_assignee_id = None


def pre_branch_distribute(db, t, u):
    _req(u.role == Role.BRANCH_ADMIN and _branch_user_ok(u, t) and t.status in S.BRANCH_PHASE, "Not allowed")


def branch_distribute(db, t, u, assignee_id, now=None):
    now = _now(now); pre_branch_distribute(db, t, u)
    au = db.get(User, assignee_id)
    if not au or au.branch_id != t.branch_id or au.status != "active": raise ValidationFailed("Pick an active user of your branch")
    t.branch_assignee_id = au.id
    log(db, t, "branch_assigned_staff", u, frm=(t.status, t.level), meta={"assignee": au.id}, now=now)
    notify.to_users(db, [au.id], f"{t.number} assigned to you", t, "assignment")
    return t


def pre_verify(db, t, u):
    _req(not is_branch(u) and (is_admin(u) or user_level(u) == 2) and t.status == S.ACTION_TAKEN, "Nothing to verify")


def verify(db, t, u, approve, note=None, action_taken=None, outcome=None, root_cause=None, now=None):
    now = _now(now); pre_verify(db, t, u)
    if approve:
        return _do_resolve(db, t, u, action_taken or "Branch action verified", outcome or _text(note, "Outcome", 3),
                           root_cause, False, now, etype="verified_resolved")
    note = _text(note, "Reason for rejecting", 5)
    _transition(db, t, u, "verification_rejected", S.ASSIGNED_BRANCH, now, note=note)
    notify.to_branch(db, t.branch_id, f"{t.number}: Head Office needs more action - {note[:120]}", t, "assignment")
    return t


def pre_resolve(db, t, u):
    _req(not is_branch(u), "Branch users cannot resolve; mark Action Taken instead")
    _req(t.status in (set(S.QUEUE.values()) | set(S.WORKING.values()) | {S.ASSIGNED_BRANCH, S.BRANCH_ACK}),
         "Complaint cannot be resolved from this status")
    _req(at_level(u, t), "Only the owning level can resolve")
    if t.status in S.WORKING.values():
        _req(t.owner_id in (None, u.id) or is_admin(u) or (u.is_team_lead and user_level(u) == t.level),
             "This complaint is being worked by someone else")


def resolve_ticket(db, t, u, action_taken=None, outcome=None, root_cause=None, first_call=False, now=None):
    now = _now(now); pre_resolve(db, t, u)
    return _do_resolve(db, t, u, action_taken, outcome, root_cause, first_call, now)


def _do_resolve(db, t, u, action_taken, outcome, root_cause, first_call, now, etype="resolved"):
    action_taken = _text(action_taken, "Action taken", 3)
    outcome = _text(outcome, "Outcome", 3)
    lvl = t.level
    _transition(db, t, u, etype, S.RESOLVED, now, note=outcome, meta={"first_call": bool(first_call)})
    t.resolved_at, t.resolved_level = now, lvl
    t.resolution_action, t.resolution_outcome, t.root_cause = action_taken, outcome, root_cause
    t.resolved_on_first_call = bool(first_call)
    notify.to_customer(db, t, f"Your complaint {t.number} has been resolved. Reply if the issue persists; "
                              f"otherwise it will be closed automatically.")
    notify.to_branch(db, t.branch_id, f"{t.number} resolved", t)
    return t


def pre_close(db, t, u):
    _req(t.status == S.RESOLVED, "Only a resolved complaint can be closed")
    _req(not is_branch(u) and (is_admin(u) or user_level(u) == 3 or (user_level(u) == 2 and t.priority != "critical")),
         "You cannot close this complaint")


def close(db, t, u, now=None):
    now = _now(now); pre_close(db, t, u)
    _transition(db, t, u, "closed", S.CLOSED, now, rearm=False)
    t.closed_at, t.due_at = now, None
    return t


def pre_reopen(db, t, u, now=None):
    _req(t.status in (S.RESOLVED, S.CLOSED), "Only resolved or closed complaints can be reopened")
    _req(not is_branch(u) and (is_admin(u) or user_level(u) in (2, 3)), "Only L2, L3 or Admin can reopen")


def reopen(db, t, u, reason, now=None, system=False):
    now = _now(now)
    if not system: pre_reopen(db, t, u, now)
    reason = _text(reason, "Reason", 3)
    c = cfgs.cfg(db)
    ref = t.closed_at or t.resolved_at
    if (system or not is_admin(u)) and ref and now - ref > timedelta(days=c["reopen_window_days"]):
        raise ValidationFailed("The reopen window has passed")
    lvl = t.resolved_level or 2
    _transition(db, t, u if not system else None, "reopened", S.QUEUE[lvl], now, owner=None, reason=reason,
                trigger="system" if system else "manual", actor_type="customer" if system else None)
    t.reopen_count = (t.reopen_count or 0) + 1
    t.closed_at = None
    t.cooling = False
    notify.to_level(db, lvl, f"{t.number} reopened: {reason}", t, "reopen")
    return t


def pre_await_customer(db, t, u):
    _req(not is_branch(u) and at_level(u, t), "Only the owning level can pause for the customer")
    _req(t.status in (set(S.QUEUE.values()) | set(S.WORKING.values()) | {S.ASSIGNED_BRANCH, S.BRANCH_ACK}),
         "Cannot pause in this status")


def await_customer(db, t, u, reason, now=None):
    now = _now(now); pre_await_customer(db, t, u)
    reason = _text(reason, "Reason", 3)
    _pause(db, t, u, S.AWAITING_CUSTOMER, now, reason)
    return t


def _pause(db, t, u, new, now, reason, extra_minutes=None):
    cal = cfgs.calendar(db)
    t.remaining_minutes = working_minutes_between(now, t.due_at, cal) if t.due_at else None
    t.paused_from_status = t.status
    _transition(db, t, u, "paused", new, now, reason=reason, rearm=(new == S.AWAITING_BRANCH_INFO),
               meta={"kind": new})
    if new == S.AWAITING_CUSTOMER: t.due_at = None


def pre_return_for_info(db, t, u):
    _req(not is_branch(u) and (is_admin(u) or user_level(u) == 1) and t.level == 1, "Only L1 can ask the branch")
    _req(t.origin_branch_id is not None, "This complaint was not registered by a branch")
    _req(t.status in (S.L1_QUEUE, S.L1_WORKING), "Complaint is not at L1")


def return_for_info(db, t, u, question, now=None):
    now = _now(now); pre_return_for_info(db, t, u)
    question = _text(question, "Question", 5)
    _pause(db, t, u, S.AWAITING_BRANCH_INFO, now, question)
    db.add(Message(ticket_id=t.id, channel="thread", author_id=u.id, body=question, created_at=now))
    notify.to_branch(db, t.origin_branch_id, f"{t.number}: Head Office needs information - {question[:100]}", t, "info_request")
    return t


def pre_resume(db, t, u):
    _req(t.status in S.PAUSED, "Complaint is not paused")
    ok = (not is_branch(u) and (is_admin(u) or user_level(u) == t.level)) or \
         (t.status == S.AWAITING_BRANCH_INFO and is_branch(u) and u.branch_id == t.origin_branch_id)
    _req(ok, "Not allowed to resume")


def resume(db, t, u, now=None, system=False):
    now = _now(now)
    if not system: pre_resume(db, t, u)
    back = t.paused_from_status or S.QUEUE[t.level or 1]
    rem = t.remaining_minutes
    _transition(db, t, u if not system else None, "resumed", back, now, rearm=False,
                trigger="system" if system else "manual", actor_type="customer" if system else None)
    arm(db, t, now, minutes=rem if rem and rem > 0 else None)
    t.paused_from_status = t.remaining_minutes = None
    return t


def pre_forward(db, t, u):
    _req(t.status == S.DRAFT and is_branch(u) and u.branch_id == t.origin_branch_id, "Nothing to forward")


def forward(db, t, u, now=None):
    now = _now(now); pre_forward(db, t, u)
    _transition(db, t, u, "forwarded", S.L1_QUEUE, now, level=1, note="Forwarded to Head Office")
    t.forwarded_at = now
    notify.to_customer(db, t, f"We have registered your complaint {t.number}. We will update you shortly.")
    if t.urgent_flag:
        notify.to_level(db, 1, f"URGENT: {t.number} forwarded by a branch", t, "alert", True)
        notify.to_level(db, 2, f"URGENT: {t.number} forwarded by a branch", t, "alert", True)
    return t


def pre_withdraw(db, t, u):
    _req(t.status == S.L1_QUEUE and t.owner_id is None and is_branch(u) and u.branch_id == t.origin_branch_id
         and t.forwarded_at is not None, "It can only be withdrawn before L1 picks it up")


def withdraw(db, t, u, now=None):
    now = _now(now); pre_withdraw(db, t, u)
    _transition(db, t, u, "withdrawn", S.DRAFT, now, rearm=False)
    t.due_at, t.forwarded_at = None, None
    return t


def pre_set_priority(db, t, u):
    _req(is_ho(u) and not is_branch(u) and t.status in S.OPEN, "Not allowed")


def set_priority(db, t, u, priority, now=None):
    now = _now(now); pre_set_priority(db, t, u)
    if priority not in PRIORITIES: raise ValidationFailed("invalid priority")
    old = t.priority; t.priority = priority
    if _is_timed(t.status) and t.status not in (S.RESOLVED, S.AWAITING_BRANCH_INFO, S.ASSIGNED_BRANCH, S.BRANCH_ACK):
        arm(db, t, now)
    log(db, t, "priority_changed", u, frm=(t.status, t.level), now=now, meta={"from": old, "to": priority})
    return t


def pre_merge(db, t, u):
    _req(is_ho(u) and not is_branch(u) and (t.status in S.OPEN or t.status == S.RESOLVED), "Not allowed")


def merge(db, t, u, into_id, now=None):
    now = _now(now); pre_merge(db, t, u)
    target = db.get(Ticket, into_id)
    if not target or target.id == t.id or target.status in (S.CLOSED, S.DRAFT): raise ValidationFailed("Invalid merge target")
    _transition(db, t, u, "merged", S.CLOSED, now, via="merge", rearm=False, meta={"into": target.number})
    t.merged_into_id, t.closed_at, t.due_at = target.id, now, None
    log(db, target, "merge_received", u, frm=(target.status, target.level), now=now, note=f"Merged from {t.number}")
    return t


def pre_update_details(db, t, u):
    ok = (is_ho(u) and not is_branch(u) and at_level(u, t) and t.status in S.OPEN) or \
         (is_branch(u) and t.status == S.DRAFT and u.branch_id == t.origin_branch_id)
    _req(ok, "Not allowed to edit details")


def update_details(db, t, u, now=None, **fields):
    now = _now(now); pre_update_details(db, t, u)
    changed = {}
    for k, v in fields.items():
        if k not in DETAIL_FIELDS: raise ValidationFailed(f"{k} cannot be edited (the original description is immutable)")
        old = getattr(t, k)
        if k in ("receiver_mobile", "caller_number"): v = norm_mobile(v)
        if (old or None) != (v or None):
            changed[k] = {"from": old, "to": v}; setattr(t, k, v or None)
    if not changed:
        raise ValidationFailed("No changes to save")
    t.incomplete = _is_incomplete(t)
    log(db, t, "details_updated", u, frm=(t.status, t.level), meta=changed, now=now)
    _touch(db, t, u, now)
    return t


def pre_admin_force(db, t, u): _req(is_admin(u), "Admin only")


def admin_force(db, t, u, to_status, reason, to_level=None, now=None):
    now = _now(now); pre_admin_force(db, t, u)
    reason = _text(reason, "Reason", 5)
    if to_status not in S.ALL: raise ValidationFailed("unknown status")
    owner = None if to_status in S.QUEUE.values() else KEEP
    _transition(db, t, u, "admin_force", to_status, now, level=to_level, via="admin_force", trigger="admin_force",
                reason=reason, owner=owner, rearm=to_status not in (S.CLOSED, S.DRAFT))
    if to_status == S.CLOSED: t.closed_at, t.due_at = now, None
    return t


# registry used by the API and by `available_actions` (UI buttons) -- one source of truth
ACTIONS = {
    "pick": (pre_pick, pick), "release": (pre_release, release), "escalate": (pre_escalate, escalate),
    "deescalate": (pre_deescalate, deescalate), "assign_branch": (pre_assign_branch, assign_branch),
    "extend_deadline": (pre_extend, extend_deadline), "branch_ack": (pre_branch_ack, branch_ack),
    "branch_action_taken": (pre_branch_action, branch_action_taken), "branch_return": (pre_branch_return, branch_return),
    "branch_distribute": (pre_branch_distribute, branch_distribute), "verify": (pre_verify, verify),
    "resolve": (pre_resolve, resolve_ticket), "close": (pre_close, close), "reopen": (pre_reopen, reopen),
    "await_customer": (pre_await_customer, await_customer), "return_for_info": (pre_return_for_info, return_for_info),
    "resume": (pre_resume, resume), "forward": (pre_forward, forward), "withdraw": (pre_withdraw, withdraw),
    "set_priority": (pre_set_priority, set_priority), "merge": (pre_merge, merge),
    "update_details": (pre_update_details, update_details), "admin_force": (pre_admin_force, admin_force),
}


def available_actions(db, t, u) -> list[str]:
    out = []
    for name, (pre, _fn) in ACTIONS.items():
        try:
            pre(db, t, u)
            out.append(name)
        except NotAllowed:
            pass
    return out


def run_action(db, t, u, name, params=None, expected_version=None):
    if name not in ACTIONS: raise ValidationFailed(f"unknown action {name}")
    if expected_version is not None and t.version != expected_version:
        raise Conflict("This complaint was changed by someone else. Reload and try again.")
    params = dict(params or {})
    fn = ACTIONS[name][1]
    if name == "resolve": params.setdefault("first_call", False)
    try:
        return fn(db, t, u, **params)
    except TypeError as e:
        raise ValidationFailed(f"Invalid parameters for {name}: {e}")


# ---------------------------------------------------------------------------------------------
# messaging
# ---------------------------------------------------------------------------------------------
def post_message(db, u, t, channel, body, now=None):
    now = _now(now)
    body = _text(body, "Message", 1)
    if channel == "thread":
        _req(is_ho(u) or (is_branch(u) and branch_can_write(db, u, t) and t.status != S.DRAFT), "Cannot post to this thread")
    elif channel == "note":
        _req(is_ho(u) and not is_branch(u), "Notes are for Head Office only")
    elif channel == "customer_out":
        _req(not is_branch(u) and is_ho(u), "Only Head Office can message the customer")
    else:
        raise ValidationFailed("unknown channel")
    m = Message(ticket_id=t.id, channel=channel, author_id=u.id, body=body, created_at=now)
    db.add(m); db.flush()
    if channel == "customer_out": notify.to_customer(db, t, body)
    if channel == "thread":
        if is_branch(u):
            if t.owner_id: notify.to_users(db, [t.owner_id], f"{t.number}: new message from branch", t, "message")
            else: notify.to_level(db, t.level or 1, f"{t.number}: new message from branch", t, "message")
        else:
            notify.to_branch(db, t.branch_id or t.origin_branch_id, f"{t.number}: message from Head Office", t, "message")
        if is_branch(u) and t.status == S.AWAITING_BRANCH_INFO and u.branch_id == t.origin_branch_id:
            resume(db, t, u, now=now)
    _touch(db, t, u, now)
    log(db, t, "message", u, frm=(t.status, t.level), now=now, meta={"channel": channel, "message_id": m.id})
    return m


# ---------------------------------------------------------------------------------------------
# customer events (intake channels) and system actions
# ---------------------------------------------------------------------------------------------
def customer_reply(db, t, body, now=None, channel="customer_in"):
    """A customer wrote back on WhatsApp / email. Attach to the existing complaint, never create a new one."""
    now = _now(now)
    m = Message(ticket_id=t.id, channel="customer_in", author_type="customer", body=body or "(no text)", created_at=now)
    db.add(m); db.flush()
    log(db, t, "customer_reply", None, frm=(t.status, t.level), now=now, actor_type="customer", meta={"message_id": m.id})
    outcome = "attached"
    if t.status == S.AWAITING_CUSTOMER:
        resume(db, t, None, now=now, system=True); outcome = "resumed"
    elif t.status in (S.RESOLVED, S.CLOSED):
        try:
            reopen(db, t, None, "Customer replied after resolution", now=now, system=True); outcome = "reopened"
        except ValidationFailed:
            outcome = "window_passed"
    else:
        notify.to_users(db, [t.owner_id], f"{t.number}: customer replied", t, "customer_reply")
        if t.owner_id is None: notify.to_level(db, t.level or 1, f"{t.number}: customer replied", t, "customer_reply")
    return outcome


def customer_confirm(db, t, now=None):
    now = _now(now)
    if t.status != S.RESOLVED: raise InvalidTransition("Not resolved")
    _transition(db, t, None, "closed", S.CLOSED, now, rearm=False, trigger="system", actor_type="customer",
                note="Customer confirmed resolution")
    t.closed_at, t.due_at = now, None


def auto_close(db, t, now):
    _transition(db, t, None, "auto_closed", S.CLOSED, now, rearm=False, trigger="system",
                note="Auto-closed after the confirmation period")
    t.closed_at, t.due_at = now, None


def auto_escalate(db, t, now, trigger="auto_sla"):
    frm = t.level
    _transition(db, t, None, "escalated", S.QUEUE[frm + 1], now, owner=None, trigger=trigger,
                reason=f"Unattended beyond the L{frm} threshold" if trigger == "auto_sla" else "Branch deadline missed",
                meta={"rule": trigger})
    t.escalation_count = (t.escalation_count or 0) + 1
    t.cooling = False
    msg = f"{t.number} auto-escalated to L{frm + 1} (unattended)"
    notify.to_level(db, frm + 1, msg, t, "escalation")
    notify.to_level(db, frm, msg, t, "escalation", team_leads_only=True)
    notify.to_users(db, [t.owner_id], msg, t, "escalation")
    t.owner_id = None


def release_user_tickets(db, user, actor=None, now=None):
    """Owner left or went on leave: nothing may be orphaned."""
    now = _now(now); n = 0
    for t in db.query(Ticket).filter(Ticket.owner_id == user.id, Ticket.status.in_(list(S.OPEN))).all():
        if t.status in S.WORKING.values():
            _transition(db, t, actor, "owner_released", S.QUEUE[t.level], now, owner=None, trigger="system",
                        reason="Owner deactivated or on leave")
        else:
            t.owner_id = None
            log(db, t, "owner_released", actor, frm=(t.status, t.level), now=now, reason="Owner deactivated or on leave")
        notify.to_level(db, t.level or 1, f"{t.number} is back in the queue (owner unavailable)", t, "alert", True)
        n += 1
    for t in db.query(Ticket).filter(Ticket.branch_assignee_id == user.id, Ticket.status.in_(list(S.OPEN))).all():
        t.branch_assignee_id = None
        log(db, t, "assignee_released", actor, frm=(t.status, t.level), now=now, reason="Branch user deactivated")
        notify.to_branch(db, t.branch_id, f"{t.number} is unassigned: redistribute it", t, "alert", True); n += 1
    return n


def release_branch_tickets(db, branch, actor=None, now=None):
    """Branch suspended: its open assignments go back to L2."""
    now = _now(now); n = 0
    for t in db.query(Ticket).filter(Ticket.branch_id == branch.id, Ticket.status.in_(list(S.BRANCH_PHASE))).all():
        _withdraw_branch_quiet(db, t)
        _transition(db, t, actor, "branch_suspended", S.L2_QUEUE, now, owner=None, trigger="system",
                    reason=f"Branch {branch.code} suspended")
        notify.to_level(db, 2, f"{t.number} returned to L2: branch {branch.code} suspended", t, "alert")
        n += 1
    return n
