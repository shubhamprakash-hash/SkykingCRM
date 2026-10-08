from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import current_user
from app.enums import Role
from app.models import User, StaffInvitation, Branch
from app.serializers import user_out, iso
from app.services import onboarding, notify
from app.services.errors import NotFound, NotAllowed, ValidationFailed

router = APIRouter(prefix="/api", tags=["users"])


@router.get("/users")
def users(db: Session = Depends(get_db), u: User = Depends(current_user)):
    q = db.query(User)
    if u.role in Role.BRANCH:
        if u.role != Role.BRANCH_ADMIN: raise NotAllowed("Not allowed")
        q = q.filter(User.branch_id == u.branch_id)
    elif u.role not in Role.ADMIN:
        raise NotAllowed("Not allowed")
    return [user_out(x) for x in q.order_by(User.name)]


@router.get("/users/directory")
def directory(level: int | None = None, db: Session = Depends(get_db), u: User = Depends(current_user)):
    """Active Head Office users (for 'send back to a named person'); branch users get their own branch colleagues."""
    if u.role in Role.BRANCH:
        rows = db.query(User).filter(User.branch_id == u.branch_id, User.status == "active")
    else:
        rows = db.query(User).filter(User.status == "active", User.role.in_(list(Role.HO_LEVEL)))
        if level: rows = rows.filter(User.role == f"L{level}")
    return [{"id": x.id, "name": x.name, "role": x.role} for x in rows.order_by(User.name)]


class InviteBody(BaseModel):
    name: str
    role: str
    email: str | None = None
    mobile: str | None = None
    branch_id: int | None = None
    region_id: int | None = None


def inv_out(i, db):
    br = db.get(Branch, i.branch_id) if i.branch_id else None
    return {"id": i.id, "name": i.name, "role": i.role, "email": i.email, "mobile": i.mobile, "status": i.status,
            "branch": br.name if br else None, "branch_id": i.branch_id, "expires_at": iso(i.expires_at), "purpose": i.purpose}


@router.post("/invitations", status_code=201)
def invite(body: InviteBody, db: Session = Depends(get_db), u: User = Depends(current_user)):
    inv, raw = onboarding.invite(db, u, name=body.name, role=body.role, email=body.email, mobile=body.mobile, branch_id=body.branch_id)
    db.commit()
    link = f"/accept-invite?token={raw}"
    return {**inv_out(inv, db), "invite_link": link,
            "note": "Share this link with the invitee (it is also what the WhatsApp/email invitation contains)."}


@router.get("/invitations")
def invitations(db: Session = Depends(get_db), u: User = Depends(current_user)):
    q = db.query(StaffInvitation).filter(StaffInvitation.purpose == "invite")
    if u.role in Role.BRANCH:
        if u.role != Role.BRANCH_ADMIN: raise NotAllowed("Not allowed")
        q = q.filter(StaffInvitation.branch_id == u.branch_id)
    elif u.role not in Role.ADMIN:
        raise NotAllowed("Not allowed")
    return [inv_out(i, db) for i in q.order_by(StaffInvitation.id.desc()).limit(200)]


def _inv(db, iid):
    i = db.get(StaffInvitation, iid)
    if not i: raise NotFound("Invitation not found")
    return i


@router.post("/invitations/{iid}/approve")
def approve(iid: int, db: Session = Depends(get_db), u: User = Depends(current_user)):
    i = onboarding.approve(db, u, _inv(db, iid)); db.commit(); return inv_out(i, db)


@router.post("/invitations/{iid}/revoke")
def revoke(iid: int, db: Session = Depends(get_db), u: User = Depends(current_user)):
    i = _inv(db, iid); onboarding.revoke(db, u, i); db.commit(); return inv_out(i, db)


class UserPatch(BaseModel):
    status: str | None = None
    is_team_lead: bool | None = None


@router.patch("/users/{uid}")
def patch_user(uid: int, body: UserPatch, db: Session = Depends(get_db), u: User = Depends(current_user)):
    target = db.get(User, uid)
    if not target: raise NotFound("User not found")
    released = 0
    if body.status: released = onboarding.set_user_status(db, u, target, body.status)
    if body.is_team_lead is not None:
        if u.role not in Role.ADMIN: raise NotAllowed("Admin only")
        target.is_team_lead = body.is_team_lead
    db.commit()
    return {**user_out(target), "tickets_released": released}


@router.post("/users/{uid}/reset-password")
def reset_pw(uid: int, db: Session = Depends(get_db), u: User = Depends(current_user)):
    target = db.get(User, uid)
    if not target: raise NotFound("User not found")
    raw = onboarding.password_reset_token(db, u, target); db.commit()
    return {"reset_link": f"/accept-invite?token={raw}"}


@router.get("/notifications")
def notifications(unread: bool = False, db: Session = Depends(get_db), u: User = Depends(current_user)):
    from app.models import Notification
    q = db.query(Notification).filter_by(user_id=u.id)
    if unread: q = q.filter_by(read=False)
    rows = q.order_by(Notification.id.desc()).limit(50).all()
    return {"unread": db.query(Notification).filter_by(user_id=u.id, read=False).count(),
            "items": [{"id": n.id, "ticket_id": n.ticket_id, "kind": n.kind, "text": n.text, "at": iso(n.created_at), "read": n.read} for n in rows]}


@router.post("/notifications/read")
def read_all(db: Session = Depends(get_db), u: User = Depends(current_user)):
    from app.models import Notification
    db.query(Notification).filter_by(user_id=u.id, read=False).update({"read": True}); db.commit(); return {"ok": True}
