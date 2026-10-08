"""Branches onboard Head Office; branch admins onboard their own staff."""
import csv, io
from datetime import timedelta
from sqlalchemy.orm import Session
from app.enums import Role
from app.models import StaffInvitation, User, Branch, BranchPincode, Region, AuditLog
from app.security import utcnow, new_token, hash_token, hash_password, check_password_policy
from app.services import settings_service as cfgs, workflow as wf
from app.services.errors import NotAllowed, ValidationFailed, NotFound

BRANCH_ROLES = (Role.BRANCH_ADMIN, Role.BRANCH_STAFF)
HO_CREATABLE = Role.BRANCH.union(Role.HO_LEVEL).union({Role.REGIONAL_MANAGER, Role.HO_ADMIN})


def audit(db, actor, action, detail=None):
    db.add(AuditLog(actor_id=actor.id if actor else None, action=action, detail=detail or {}))


def invite(db: Session, inviter: User, *, name, role, email=None, mobile=None, branch_id=None, now=None):
    now = now or utcnow()
    if not (email or mobile): raise ValidationFailed("Email or mobile is required")
    mobile = wf.norm_mobile(mobile); email = (email or "").strip().lower() or None
    if inviter.role in Role.BRANCH:
        if inviter.role != Role.BRANCH_ADMIN: raise NotAllowed("Only a Branch Admin can invite staff")
        if role not in BRANCH_ROLES: raise NotAllowed("A branch cannot create Head Office users")
        branch_id = inviter.branch_id                               # a branch can only invite into its own branch
    elif inviter.role in Role.ADMIN:
        if role not in HO_CREATABLE or (role == Role.HO_ADMIN and inviter.role != Role.SUPER_ADMIN):
            raise NotAllowed("This role cannot be invited")
        if role in BRANCH_ROLES and not branch_id: raise ValidationFailed("Branch is required")
    else:
        raise NotAllowed("Not allowed to invite users")
    if branch_id and not db.get(Branch, branch_id): raise NotFound("Branch not found")
    if (email and db.query(User).filter(User.email == email).first()) or (mobile and db.query(User).filter(User.mobile == mobile).first()):
        raise ValidationFailed("A user with this email or mobile already exists")
    c = cfgs.cfg(db)
    needs = inviter.role in Role.BRANCH and (c["staff_approval"] == "all" or
                                              (c["staff_approval"] == "branch_admin" and role == Role.BRANCH_ADMIN))
    raw, hashed = new_token()
    inv = StaffInvitation(purpose="invite", branch_id=branch_id, name=name, email=email, mobile=mobile, role=role,
                          token_hash=hashed, expires_at=now + timedelta(hours=c["invite_hours"]), invited_by=inviter.id,
                          status="awaiting_approval" if needs else "pending", created_at=now)
    db.add(inv); db.flush()
    audit(db, inviter, "invite_created", {"invitation": inv.id, "role": role, "branch_id": branch_id, "needs_approval": needs})
    return inv, raw


def approve(db: Session, approver: User, inv: StaffInvitation, raw_token_holder=None):
    if approver.role not in Role.ADMIN: raise NotAllowed("Head Office approval required")
    if inv.status != "awaiting_approval": raise ValidationFailed("Nothing to approve")
    inv.status, inv.approved_by = "pending", approver.id
    audit(db, approver, "invite_approved", {"invitation": inv.id})
    return inv


def revoke(db: Session, actor: User, inv: StaffInvitation):
    if actor.role in Role.BRANCH and (actor.role != Role.BRANCH_ADMIN or inv.branch_id != actor.branch_id): raise NotAllowed("Not allowed")
    if actor.role not in Role.BRANCH and actor.role not in Role.ADMIN: raise NotAllowed("Not allowed")
    if inv.status in ("accepted",): raise ValidationFailed("Already accepted")
    inv.status = "revoked"; audit(db, actor, "invite_revoked", {"invitation": inv.id})


def accept(db: Session, raw_token: str, password: str, now=None) -> User:
    now = now or utcnow()
    inv = db.query(StaffInvitation).filter_by(token_hash=hash_token(raw_token)).first()
    if not inv or inv.status in ("revoked", "accepted") or (inv.expires_at and inv.expires_at < now):
        raise ValidationFailed("This invitation is invalid or has expired")
    if inv.status == "awaiting_approval": raise ValidationFailed("This invitation is waiting for Head Office approval")
    err = check_password_policy(password)
    if err: raise ValidationFailed(err)
    if inv.purpose == "reset":
        u = db.get(User, inv.user_id); u.password_hash = hash_password(password); u.failed_attempts = 0; u.locked_until = None
    else:
        u = User(name=inv.name, email=inv.email, mobile=inv.mobile, role=inv.role, branch_id=inv.branch_id,
                 password_hash=hash_password(password), status="active", created_at=now)
        db.add(u); db.flush(); inv.accepted_user_id = u.id
    inv.status = "accepted"
    audit(db, u, "invite_accepted", {"invitation": inv.id})
    return u


def password_reset_token(db: Session, actor: User, user: User, now=None):
    now = now or utcnow()
    if actor.role not in Role.ADMIN and not (actor.role == Role.BRANCH_ADMIN and user.branch_id == actor.branch_id and user.role in BRANCH_ROLES):
        raise NotAllowed("Not allowed")
    raw, hashed = new_token()
    db.add(StaffInvitation(purpose="reset", user_id=user.id, token_hash=hashed, status="pending", invited_by=actor.id,
                           expires_at=now + timedelta(hours=cfgs.cfg(db)["invite_hours"])))
    audit(db, actor, "password_reset_issued", {"user": user.id})
    return raw


def set_user_status(db: Session, actor: User, user: User, status: str, now=None):
    if status not in ("active", "suspended"): raise ValidationFailed("invalid status")
    if actor.role in Role.BRANCH:
        if actor.role != Role.BRANCH_ADMIN or user.branch_id != actor.branch_id or user.id == actor.id: raise NotAllowed("Not allowed")
    elif actor.role not in Role.ADMIN: raise NotAllowed("Not allowed")
    user.status = status
    n = wf.release_user_tickets(db, user, actor, now) if status == "suspended" else 0
    audit(db, actor, f"user_{status}", {"user": user.id, "tickets_released": n})
    return n


def import_branches_csv(db: Session, actor: User, text: str) -> dict:
    """Columns: code,name,city,state,region,address,contact_name,contact_email,contact_phone,pincodes (pincodes separated by ;)"""
    if actor.role not in Role.ADMIN: raise NotAllowed("Admin only")
    created, updated, errors = 0, 0, []
    for i, row in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        code = (row.get("code") or "").strip().upper()
        if not code or not (row.get("name") or "").strip():
            errors.append({"row": i, "error": "code and name are required"}); continue
        region = None
        if (row.get("region") or "").strip():
            region = db.query(Region).filter_by(name=row["region"].strip()).first()
            if not region: region = Region(name=row["region"].strip()); db.add(region); db.flush()
        b = db.query(Branch).filter_by(code=code).first()
        if b: updated += 1
        else: b = Branch(code=code, name=row["name"].strip(), status="pending"); db.add(b); created += 1
        for k in ("name", "city", "state", "address", "contact_name", "contact_email", "contact_phone"):
            if (row.get(k) or "").strip(): setattr(b, k, row[k].strip())
        if region: b.region_id = region.id
        db.flush()
        for pc in [p.strip() for p in (row.get("pincodes") or "").split(";") if p.strip()]:
            if not pc.isdigit() or len(pc) != 6: errors.append({"row": i, "error": f"bad pincode {pc}"}); continue
            if not db.query(BranchPincode).filter_by(branch_id=b.id, pincode=pc).first(): db.add(BranchPincode(branch_id=b.id, pincode=pc))
    audit(db, actor, "branches_imported", {"created": created, "updated": updated, "errors": len(errors)})
    return {"created": created, "updated": updated, "errors": errors}
