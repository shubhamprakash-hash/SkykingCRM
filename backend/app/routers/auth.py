from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.config import get_settings
from app.database import get_db
from app.deps import current_user
from app.models import User, RefreshToken, StaffInvitation, Branch
from app.security import (verify_password, hash_password, make_access_token, new_token, hash_token, utcnow,
                          check_password_policy)
from app.serializers import user_out
from app.services import onboarding, workflow as wf

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Login(BaseModel):
    username: str
    password: str


def _tokens(db, u):
    s = get_settings()
    raw, hashed = new_token()
    db.add(RefreshToken(user_id=u.id, token_hash=hashed, expires_at=utcnow() + timedelta(days=s.REFRESH_TOKEN_DAYS)))
    return {"access_token": make_access_token(u.id, u.role), "refresh_token": raw, "user": user_out(u)}


@router.post("/login")
def login(body: Login, db: Session = Depends(get_db)):
    s = get_settings()
    ident = body.username.strip()
    u = db.query(User).filter(User.email == ident.lower()).first() or \
        (db.query(User).filter(User.mobile == wf.norm_mobile(ident)).first() if wf.norm_mobile(ident) else None)
    generic = HTTPException(401, "Incorrect username or password")
    if not u:
        raise generic
    now = utcnow()
    if u.locked_until and u.locked_until > now:
        raise HTTPException(423, "Account temporarily locked. Try again later.")
    if u.status != "active" or not verify_password(body.password, u.password_hash):
        if u.status == "active":
            u.failed_attempts = (u.failed_attempts or 0) + 1
            if u.failed_attempts >= s.MAX_FAILED_LOGINS:
                u.locked_until, u.failed_attempts = now + timedelta(minutes=s.LOCKOUT_MINUTES), 0
            db.commit()
        raise generic
    u.failed_attempts, u.locked_until, u.last_login = 0, None, now
    out = _tokens(db, u); db.commit()
    return out


class Refresh(BaseModel):
    refresh_token: str


@router.post("/refresh")
def refresh(body: Refresh, db: Session = Depends(get_db)):
    rt = db.query(RefreshToken).filter_by(token_hash=hash_token(body.refresh_token)).first()
    if not rt or rt.revoked or rt.expires_at < utcnow():
        raise HTTPException(401, "Session expired")
    u = db.get(User, rt.user_id)
    if not u or u.status != "active":
        raise HTTPException(401, "Session expired")
    rt.revoked = True                                   # rotation: a refresh token works once
    out = _tokens(db, u); db.commit()
    return out


@router.post("/logout")
def logout(body: Refresh, db: Session = Depends(get_db)):
    rt = db.query(RefreshToken).filter_by(token_hash=hash_token(body.refresh_token)).first()
    if rt:
        rt.revoked = True; db.commit()
    return {"ok": True}


@router.get("/me")
def me(u: User = Depends(current_user)):
    return user_out(u)


class ChangePw(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
def change_password(body: ChangePw, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, u.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    err = check_password_policy(body.new_password)
    if err:
        raise HTTPException(422, err)
    u.password_hash = hash_password(body.new_password)
    db.query(RefreshToken).filter_by(user_id=u.id, revoked=False).update({"revoked": True})   # sign out everywhere
    db.commit()
    return {"ok": True}


class Accept(BaseModel):
    token: str
    password: str


@router.get("/invite-info")
def invite_info(token: str, db: Session = Depends(get_db)):
    inv = db.query(StaffInvitation).filter_by(token_hash=hash_token(token)).first()
    if not inv or inv.status not in ("pending", "awaiting_approval") or (inv.expires_at and inv.expires_at < utcnow()):
        raise HTTPException(404, "Invitation is invalid or has expired")
    br = db.get(Branch, inv.branch_id) if inv.branch_id else None
    return {"name": inv.name, "role": inv.role, "branch": br.name if br else None, "purpose": inv.purpose,
            "awaiting_approval": inv.status == "awaiting_approval"}


@router.post("/accept-invite")
def accept_invite(body: Accept, db: Session = Depends(get_db)):
    u = onboarding.accept(db, body.token, body.password)
    db.commit()
    return {"ok": True, "email": u.email, "mobile": u.mobile}
