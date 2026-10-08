from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import get_settings

_s = get_settings()
_kw = {"connect_args": {"check_same_thread": False}} if _s.DATABASE_URL.startswith("sqlite") else {"pool_pre_ping": True}
engine = create_engine(_s.DATABASE_URL, **_kw)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
