import csv, io
from collections import Counter
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import current_user
from app.enums import Role, S
from app.models import Ticket, Branch, TicketEvent, User
from app.security import utcnow
from app.services import access
from app.services.errors import NotAllowed

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), u: User = Depends(current_user)):
    now = utcnow()
    tickets = access.visible_tickets(db, u).all()
    open_ = [t for t in tickets if t.status in S.OPEN]
    by_status = Counter(t.status for t in tickets)
    by_level = Counter(t.level for t in open_ if t.level)
    ageing = {"<1 day": 0, "1-3 days": 0, "3-7 days": 0, ">7 days": 0}
    for t in open_:
        d = (now - t.created_at).total_seconds() / 86400
        ageing["<1 day" if d < 1 else "1-3 days" if d < 3 else "3-7 days" if d < 7 else ">7 days"] += 1
    resolved = [t for t in tickets if t.resolved_at]
    res_hours = sorted((t.resolved_at - t.created_at).total_seconds() / 3600 for t in resolved)
    pct = lambda p: round(res_hours[min(len(res_hours) - 1, int(len(res_hours) * p))], 1) if res_hours else None
    ids = [t.id for t in tickets]
    auto = db.query(TicketEvent).filter(TicketEvent.ticket_id.in_(ids or [0]), TicketEvent.event_type == "escalated",
                                        TicketEvent.trigger.in_(["auto_sla", "branch_breach"])).count()
    manual = db.query(TicketEvent).filter(TicketEvent.ticket_id.in_(ids or [0]), TicketEvent.event_type == "escalated",
                                          TicketEvent.trigger.in_(["manual", "l2_direct"])).count()
    reasons = Counter(r[0] for r in db.query(TicketEvent.reason_code).filter(TicketEvent.ticket_id.in_(ids or [0]),
                                                                              TicketEvent.event_type == "deescalated"))
    out = {
        "total": len(tickets), "open": len(open_), "by_status": dict(by_status),
        "open_by_level": {f"L{k}": v for k, v in sorted(by_level.items())},
        "unassigned": sum(1 for t in open_ if t.owner_id is None and t.status in S.QUEUE.values()),
        "overdue": sum(1 for t in open_ if t.due_at and t.due_at < now),
        "ageing": ageing,
        "by_source": dict(Counter(t.source for t in tickets)),
        "mine": sum(1 for t in open_ if t.owner_id == u.id or t.branch_assignee_id == u.id),
        "resolution_hours": {"median": pct(0.5), "p90": pct(0.9), "count": len(resolved)},
        "first_call_resolution": sum(1 for t in resolved if t.resolved_on_first_call),
        "escalations": {"automatic": auto, "manual": manual},
        "deescalations_by_reason": dict(reasons),
        "repeated_movement": sum(1 for t in open_ if t.repeated_movement),
        "reopened": sum(1 for t in tickets if (t.reopen_count or 0) > 0),
    }
    if u.role not in Role.BRANCH:
        names = {b.id: b.name for b in db.query(Branch)}
        league = {}
        for t in tickets:
            for bid in {t.branch_id, t.origin_branch_id} - {None}:
                row = league.setdefault(bid, {"branch": names.get(bid), "open": 0, "resolved": 0, "hours": []})
                if t.status in S.OPEN: row["open"] += 1
                if t.resolved_at and t.branch_id == bid:
                    row["resolved"] += 1; row["hours"].append((t.resolved_at - t.created_at).total_seconds() / 3600)
        out["branch_league"] = sorted(
            [{"branch": r["branch"], "open": r["open"], "resolved": r["resolved"],
              "avg_resolution_hours": round(sum(r["hours"]) / len(r["hours"]), 1) if r["hours"] else None} for r in league.values()],
            key=lambda r: -r["open"])
    return out


@router.get("/export.csv")
def export_csv(db: Session = Depends(get_db), u: User = Depends(current_user)):
    if u.role in Role.BRANCH: raise NotAllowed("Not allowed")
    buf = io.StringIO(); wr = csv.writer(buf)
    wr.writerow(["number", "created_at_utc", "source", "status", "level", "priority", "category", "customer", "mobile",
                 "consignment", "pincode", "branch", "origin_branch", "owner", "due_at_utc", "resolved_at_utc",
                 "escalations", "deescalations", "reopened"])
    for t in access.visible_tickets(db, u).order_by(Ticket.id):
        wr.writerow([t.number, t.created_at, t.source, t.status, t.level, t.priority, t.category.name if t.category else "",
                     t.customer.name if t.customer else "", t.customer.mobile if t.customer else "", t.consignment_no,
                     t.pincode, t.branch.name if t.branch else "", t.origin_branch.name if t.origin_branch else "",
                     t.owner.name if t.owner else "", t.due_at or "", t.resolved_at or "", t.escalation_count,
                     t.deescalation_count, t.reopen_count])
    from app.services.onboarding import audit
    audit(db, u, "export_tickets", {"rows": buf.getvalue().count("\n") - 1}); db.commit()
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=complaints.csv"})
