from fastapi import Depends, HTTPException, Header
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
from app.security import decode_access_token, utcnow


def current_user(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> User:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Not authenticated")
    uid = decode_access_token(authorization[7:])
    u = db.get(User, uid) if uid else None
    if not u or u.status != "active":
        raise HTTPException(401, "Not authenticated")
    return u


def require_roles(*roles):
    def dep(u: User = Depends(current_user)) -> User:
        if u.role not in roles:
            raise HTTPException(403, "Not allowed")
        return u
    return dep
