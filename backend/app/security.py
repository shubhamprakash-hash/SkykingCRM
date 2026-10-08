import hashlib, re, secrets
from datetime import datetime, timedelta, timezone
import bcrypt
from jose import jwt, JWTError
from app.config import get_settings

ALGO = "HS256"


def utcnow() -> datetime:
    """Naive UTC. All timestamps are stored as naive UTC and shown in IST by the UI."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(pw.encode()[:72], hashed.encode())
    except ValueError:
        return False


def check_password_policy(pw: str) -> str | None:
    if len(pw) < 10:
        return "Password must be at least 10 characters"
    if not (re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw)):
        return "Password must contain letters and digits"
    if pw.lower() in {"password123", "changeme123", "1234567890"}:
        return "Password is too common"
    return None


def make_access_token(user_id: int, role: str) -> str:
    s = get_settings()
    exp = utcnow() + timedelta(minutes=s.ACCESS_TOKEN_MINUTES)
    return jwt.encode({"sub": str(user_id), "role": role, "exp": exp}, s.SECRET_KEY, algorithm=ALGO)


def decode_access_token(token: str) -> int | None:
    try:
        return int(jwt.decode(token, get_settings().SECRET_KEY, algorithms=[ALGO])["sub"])
    except (JWTError, KeyError, ValueError):
        return None


def new_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
