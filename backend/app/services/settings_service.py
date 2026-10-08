"""Rules are data: SLA thresholds, calendar and limits live in the database."""
from sqlalchemy.orm import Session
from app.models import Setting, SLAPolicy
from app.enums import PRIORITIES
from app.services.calendar import Calendar

DEFAULTS = {
    "default_minutes": 360,            # 6 hours
    "critical_minutes": 120,           # proposed shorter threshold for critical (confirm)
    "warn_pct": 0.8,
    "branch_deadline_default": 360,
    "branch_deadline_min": 120,
    "branch_deadline_max": 2880,
    "max_extensions": 2,
    "info_limit_minutes": 360,         # branch must answer an Awaiting Branch Info within this
    "l3_repeat_minutes": 360,
    "branch_breach_action": "escalate_l3",   # escalate_l3 | alert_l2
    "max_deescalations": 2,
    "repeated_movement_at": 4,
    "auto_close_hours": 48,
    "reopen_window_days": 7,
    "staff_approval": "branch_admin",  # none | branch_admin | all  (HO approval of branch-invited users)
    "invite_hours": 72,
    "min_handover_chars": 20,
}
DEFAULT_CALENDAR = {"mode": "business", "tz": "Asia/Kolkata", "start": "09:00", "end": "19:00",
                    "days": [0, 1, 2, 3, 4, 5], "holidays": []}


def cfg(db: Session) -> dict:
    row = db.get(Setting, "rules")
    return {**DEFAULTS, **((row.value if row else None) or {})}


def set_cfg(db: Session, values: dict):
    unknown = set(values) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown settings: {sorted(unknown)}")
    merged = {**cfg(db), **values}
    row = db.get(Setting, "rules")
    if row:
        row.value = merged
    else:
        db.add(Setting(key="rules", value=merged))
    db.flush()
    return merged


def calendar(db: Session) -> Calendar:
    row = db.get(Setting, "calendar")
    return Calendar.from_dict({**DEFAULT_CALENDAR, **((row.value if row else None) or {})})


def set_calendar(db: Session, values: dict):
    merged = {**DEFAULT_CALENDAR, **((db.get(Setting, "calendar").value) if db.get(Setting, "calendar") else {}), **values}
    Calendar.from_dict(merged)   # validate shape
    row = db.get(Setting, "calendar")
    if row:
        row.value = merged
    else:
        db.add(Setting(key="calendar", value=merged))
    db.flush()
    return merged


def threshold(db: Session, level: int, priority: str) -> int:
    row = db.query(SLAPolicy).filter_by(level=level, priority=priority).first()
    if row:
        return row.minutes
    c = cfg(db)
    return c["critical_minutes"] if priority == "critical" else c["default_minutes"]


def set_policy(db: Session, level: int, priority: str, minutes: int):
    if level not in (1, 2, 3) or priority not in PRIORITIES or minutes < 5:
        raise ValueError("invalid policy")
    row = db.query(SLAPolicy).filter_by(level=level, priority=priority).first()
    if row:
        row.minutes = minutes
    else:
        db.add(SLAPolicy(level=level, priority=priority, minutes=minutes))
    db.flush()


def policies(db: Session) -> list[dict]:
    return [{"level": l, "priority": p, "minutes": threshold(db, l, p)} for l in (1, 2, 3) for p in PRIORITIES]
