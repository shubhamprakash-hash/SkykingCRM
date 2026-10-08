import hmac
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.config import get_settings
from app.database import get_db
from app.deps import current_user, require_roles
from app.enums import Role, PRIORITIES
from app.models import Category, AuditLog, User, Setting
from app.serializers import iso
from app.services import settings_service as cfgs, sla, onboarding, intake_msg91, intake_email, outbox
from app.services.errors import ValidationFailed

router = APIRouter(prefix="/api", tags=["admin"])
ADMIN = require_roles(*Role.ADMIN)


@router.get("/categories")
def categories(db: Session = Depends(get_db), u: User = Depends(current_user)):
    return [{"id": c.id, "name": c.name, "default_priority": c.default_priority, "active": c.active}
            for c in db.query(Category).filter_by(active=True).order_by(Category.name)]


class CatBody(BaseModel):
    name: str
    default_priority: str = "medium"


@router.post("/categories", status_code=201)
def add_category(body: CatBody, db: Session = Depends(get_db), u: User = Depends(ADMIN)):
    if body.default_priority not in PRIORITIES: raise ValidationFailed("invalid priority")
    c = Category(name=body.name.strip(), default_priority=body.default_priority); db.add(c)
    onboarding.audit(db, u, "category_created", {"name": c.name}); db.commit()
    return {"id": c.id, "name": c.name, "default_priority": c.default_priority}


@router.get("/settings")
def get_settings_all(db: Session = Depends(get_db), u: User = Depends(ADMIN)):
    return {"rules": cfgs.cfg(db), "calendar": cfgs.calendar(db).__dict__ | {"days": list(cfgs.calendar(db).days), "holidays": list(cfgs.calendar(db).holidays)},
            "policies": cfgs.policies(db)}


@router.put("/settings/rules")
def put_rules(body: dict, db: Session = Depends(get_db), u: User = Depends(ADMIN)):
    try: merged = cfgs.set_cfg(db, body)
    except ValueError as e: raise ValidationFailed(str(e))
    onboarding.audit(db, u, "rules_changed", body); db.commit(); return merged


@router.put("/settings/calendar")
def put_calendar(body: dict, db: Session = Depends(get_db), u: User = Depends(ADMIN)):
    try: merged = cfgs.set_calendar(db, body)
    except Exception as e: raise ValidationFailed(f"Invalid calendar: {e}")
    onboarding.audit(db, u, "calendar_changed", body); db.commit(); return merged


class Policy(BaseModel):
    level: int
    priority: str
    minutes: int


@router.put("/settings/policy")
def put_policy(body: Policy, db: Session = Depends(get_db), u: User = Depends(ADMIN)):
    try: cfgs.set_policy(db, body.level, body.priority, body.minutes)
    except ValueError as e: raise ValidationFailed(str(e))
    onboarding.audit(db, u, "sla_policy_changed", body.model_dump()); db.commit(); return cfgs.policies(db)


@router.get("/audit")
def audit(limit: int = 100, db: Session = Depends(get_db), u: User = Depends(ADMIN)):
    return [{"id": a.id, "at": iso(a.at), "actor_id": a.actor_id, "action": a.action, "detail": a.detail}
            for a in db.query(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500))]


@router.post("/admin/scan")
def run_scan(db: Session = Depends(get_db), u: User = Depends(ADMIN)):
    return sla.scan(db)


@router.get("/admin/reconcile")
def reconcile(db: Session = Depends(get_db), u: User = Depends(ADMIN)):
    return sla.reconcile(db)


@router.post("/intake/msg91/sync")
def msg91_sync(db: Session = Depends(get_db), u: User = Depends(ADMIN)):
    return intake_msg91.sync(db)


def _check_secret(x_webhook_secret: str):
    s = get_settings().WEBHOOK_SECRET
    if not s or not hmac.compare_digest(x_webhook_secret or "", s):
        raise HTTPException(401, "Bad webhook secret")


@router.post("/intake/email")
async def email_webhook(request: Request, x_webhook_secret: str = Header(default=""), db: Session = Depends(get_db)):
    """Accepts a raw RFC-822 message (for mail providers that POST inbound mail)."""
    _check_secret(x_webhook_secret)
    r = intake_email.process_raw_email(db, await request.body()); db.commit(); return r


@router.post("/intake/msg91/webhook")
async def msg91_webhook(request: Request, x_webhook_secret: str = Header(default=""), db: Session = Depends(get_db)):
    _check_secret(x_webhook_secret)
    raw = await request.json()
    rule = intake_msg91.rule(db)
    if not intake_msg91.eligible(raw, rule): return {"result": "skipped"}
    r = intake_msg91.ingest(db, raw); db.commit(); return {"result": r}


@router.post("/admin/outbox")
def run_outbox(db: Session = Depends(get_db), u: User = Depends(ADMIN)):
    return outbox.deliver(db)
