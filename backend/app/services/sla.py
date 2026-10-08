"""SLA scanner: the automatic escalation engine. Safe to run repeatedly and from several workers."""
import logging
from datetime import timedelta
from sqlalchemy.orm import Session
from app.enums import S
from app.models import Ticket
from app.security import utcnow
from app.services import workflow as wf, settings_service as cfgs, notify
from app.services.calendar import add_working_minutes, working_minutes_between

log = logging.getLogger("skyking.sla")

TIMED = set(S.LEVEL_OF) | {S.AWAITING_BRANCH_INFO, S.RESOLVED}


def _due_rows(db: Session, now, limit=500):
    q = db.query(Ticket).filter(Ticket.due_at.isnot(None), Ticket.due_at <= now, Ticket.status.in_(list(TIMED)))
    try:
        return q.order_by(Ticket.due_at).with_for_update(skip_locked=True).limit(limit).all()
    except Exception:  # pragma: no cover - SQLite ignores row locks
        return q.order_by(Ticket.due_at).limit(limit).all()


def process_one(db: Session, t: Ticket, now) -> str | None:
    c = cfgs.cfg(db)
    s = t.status
    if t.due_at is None or t.due_at > now:
        return None                                           # idempotent: nothing is due
    if s in (S.L1_QUEUE, S.L1_WORKING, S.L2_QUEUE, S.L2_WORKING, S.ACTION_TAKEN):
        wf.auto_escalate(db, t, now, "auto_sla"); return "escalated"
    if s in (S.ASSIGNED_BRANCH, S.BRANCH_ACK):
        if c["branch_breach_action"] == "escalate_l3":
            wf.auto_escalate(db, t, now, "branch_breach"); return "branch_breach_escalated"
        wf.log(db, t, "branch_deadline_missed", None, frm=(t.status, t.level), now=now, trigger="branch_breach")
        notify.to_users(db, [t.owner_id], f"{t.number}: branch deadline missed", t, "alert")
        notify.to_level(db, 2, f"{t.number}: branch deadline missed", t, "alert", True)
        wf.arm(db, t, now); return "branch_alerted"
    if s in (S.L3_QUEUE, S.L3_WORKING):
        wf.log(db, t, "l3_breach_alert", None, frm=(t.status, t.level), now=now, trigger="auto_sla")
        notify.to_admins(db, f"{t.number}: L3 threshold breached and no higher level exists", t, "alert")
        notify.to_level(db, 3, f"{t.number}: L3 threshold breached", t, "alert", True)
        t.due_at = now + timedelta(minutes=c["l3_repeat_minutes"]); t.warned_at = None
        return "l3_alert"
    if s == S.AWAITING_BRANCH_INFO:
        wf.log(db, t, "branch_info_overdue", None, frm=(t.status, t.level), now=now, trigger="auto_sla")
        notify.to_level(db, 2, f"{t.number}: branch has not answered the information request", t, "alert", True)
        notify.to_users(db, [t.owner_id], f"{t.number}: branch has not answered", t, "alert")
        wf.arm(db, t, now); return "info_overdue"
    if s == S.RESOLVED:
        wf.auto_close(db, t, now); return "auto_closed"
    return None


def send_warnings(db: Session, now) -> int:
    c, cal, n = cfgs.cfg(db), cfgs.calendar(db), 0
    for t in db.query(Ticket).filter(Ticket.due_at.isnot(None), Ticket.due_at > now, Ticket.warned_at.is_(None),
                                     Ticket.status.in_(list(TIMED - {S.RESOLVED}))):
        if not t.last_activity_at:
            continue
        total = working_minutes_between(t.last_activity_at, t.due_at, cal)
        used = working_minutes_between(t.last_activity_at, now, cal)
        if total > 0 and used >= c["warn_pct"] * total:
            msg = f"{t.number}: {int(c['warn_pct'] * 100)}% of the time limit used"
            notify.to_users(db, [t.owner_id, t.branch_assignee_id], msg, t, "warning")
            if t.status in (S.ASSIGNED_BRANCH, S.BRANCH_ACK): notify.to_branch(db, t.branch_id, msg, t, "warning", True)
            else: notify.to_level(db, t.level or 1, msg, t, "warning", True)
            t.warned_at = now; n += 1
    return n


def scan(db: Session, now=None) -> dict:
    now = now or utcnow()
    result = {}
    for t in _due_rows(db, now):
        try:
            with db.begin_nested():
                r = process_one(db, t, now)
            if r: result[r] = result.get(r, 0) + 1
        except Exception:
            log.exception("SLA scan failed for ticket %s", t.id)
            result["errors"] = result.get("errors", 0) + 1
    result["warnings"] = send_warnings(db, now)
    db.commit()
    return result


def reconcile(db: Session, now=None, stale_hours=72) -> list[dict]:
    """Daily integrity check: complaints that break the 'nothing without an owner level and a clock' rule."""
    now = now or utcnow(); issues = []
    for t in db.query(Ticket).filter(Ticket.status.in_(list(S.OPEN))):
        if t.status in TIMED and t.due_at is None:
            issues.append({"ticket": t.number, "issue": "no timer"})
        if t.status in S.PAUSED and not t.paused_from_status:
            issues.append({"ticket": t.number, "issue": "paused without resume state"})
        if t.status in S.LEVEL_OF and t.level != S.LEVEL_OF[t.status]:
            issues.append({"ticket": t.number, "issue": "level does not match status"})
        if t.status in S.WORKING.values() and t.owner_id is None:
            issues.append({"ticket": t.number, "issue": "working without owner"})
        if t.last_activity_at and now - t.last_activity_at > timedelta(hours=stale_hours) and t.status != S.AWAITING_CUSTOMER:
            issues.append({"ticket": t.number, "issue": f"no activity for {stale_hours}h"})
    return issues
