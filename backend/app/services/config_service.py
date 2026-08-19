"""
Loads the eligibility filter (origin / inbox_id / assignee_type /
assignee_id) from the system_config table, seeding it with the defaults
from Settings on first run. This is what makes the "which tickets enter the
CRM" rule a configuration instead of hardcoded logic (spec section 21).
"""
from sqlalchemy.orm import Session
from app.models.models import SystemConfig
from app.core.config import get_settings

settings = get_settings()

DEFAULTS = {
    "origin": settings.DEFAULT_ORIGIN,
    "whatsapp_inbox_id": str(settings.DEFAULT_WHATSAPP_INBOX_ID),
    "assignee_type": settings.DEFAULT_ASSIGNEE_TYPE,
    "support_team_id": str(settings.DEFAULT_SUPPORT_TEAM_ID),
}


def ensure_defaults(db: Session):
    for key, value in DEFAULTS.items():
        existing = db.query(SystemConfig).filter(SystemConfig.key == key).first()
        if not existing:
            db.add(SystemConfig(key=key, value=value))
    db.commit()


def get_eligibility_rule(db: Session) -> dict:
    ensure_defaults(db)
    rows = db.query(SystemConfig).filter(SystemConfig.key.in_(DEFAULTS.keys())).all()
    rule = {row.key: row.value for row in rows}
    return {
        "origin": rule.get("origin", DEFAULTS["origin"]),
        "whatsapp_inbox_id": int(rule.get("whatsapp_inbox_id", DEFAULTS["whatsapp_inbox_id"])),
        "assignee_type": rule.get("assignee_type", DEFAULTS["assignee_type"]),
        "support_team_id": rule.get("support_team_id", DEFAULTS["support_team_id"]),
    }


def is_eligible(msg91_ticket_raw: dict, rule: dict) -> bool:
    """
    Implements: origin=whatsapp AND inbox_id=<configured> AND
    assignee_type=team AND assignee_id=<configured support team id>.
    Bot-assigned / unassigned tickets are excluded by construction, since
    assignee_type must equal the configured value (team).
    """
    if msg91_ticket_raw.get("origin") != rule["origin"]:
        return False

    inbox_ids = [i.get("inbox_id") for i in msg91_ticket_raw.get("inbox_ids", [])]
    if rule["whatsapp_inbox_id"] not in inbox_ids:
        return False

    if str(msg91_ticket_raw.get("assignee_type")) != rule["assignee_type"]:
        return False

    if str(msg91_ticket_raw.get("assignee_id")) != str(rule["support_team_id"]):
        return False

    return True
