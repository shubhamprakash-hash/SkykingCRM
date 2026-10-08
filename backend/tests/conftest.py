import os
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["APP_ENV"] = "development"
os.environ["SECRET_KEY"] = "test-secret-key-test-secret-key-test"
os.environ["WEBHOOK_SECRET"] = "hook-secret"
os.environ["UPLOAD_DIR"] = "/tmp/skyking-test-uploads"

from datetime import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app import models as m
from app.security import hash_password

# Monday 12 Oct 2026, 10:00 IST  (04:30 UTC). Business hours Mon-Sat 09:00-19:00 IST.
T0 = datetime(2026, 10, 12, 4, 30)
PW = "Correct-horse-9"
PW_HASH = hash_password(PW)


def mk_user(db, name, role, branch=None, region=None, lead=False):
    u = m.User(name=name, email=f"{name.lower()}@example.com", mobile=None, role=role, branch_id=branch.id if branch else None,
               region_id=region, status="active", is_team_lead=lead, password_hash=PW_HASH)
    db.add(u); db.flush()
    return u


@pytest.fixture()
def engine():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(e)
    yield e
    e.dispose()


@pytest.fixture()
def SessionMaker(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def db(SessionMaker):
    s = SessionMaker()
    yield s
    s.close()


class World:
    pass


@pytest.fixture()
def w(db):
    w = World()
    r = m.Region(name="West"); r2 = m.Region(name="East"); db.add_all([r, r2]); db.flush()
    w.region, w.region2 = r, r2
    w.A = m.Branch(code="MUM01", name="Mumbai Andheri", city="Mumbai", state="MH", status="live", region_id=r.id)
    w.B = m.Branch(code="KOL01", name="Kolkata Salt Lake", city="Kolkata", state="WB", status="live", region_id=r2.id)
    w.C = m.Branch(code="DEL01", name="Delhi", city="Delhi", state="DL", status="pending", region_id=r.id)
    db.add_all([w.A, w.B, w.C]); db.flush()
    db.add(m.BranchPincode(branch_id=w.A.id, pincode="400053"))
    w.cat = m.Category(name="Delay", default_priority="medium"); w.cat2 = m.Category(name="Damage", default_priority="high")
    db.add_all([w.cat, w.cat2])
    w.admin = mk_user(db, "Admin", "SUPER_ADMIN")
    w.l1 = mk_user(db, "L1a", "L1"); w.l1b = mk_user(db, "L1b", "L1"); w.l1lead = mk_user(db, "L1lead", "L1", lead=True)
    w.l2 = mk_user(db, "L2a", "L2"); w.l2b = mk_user(db, "L2b", "L2"); w.l2lead = mk_user(db, "L2lead", "L2", lead=True)
    w.l3 = mk_user(db, "L3a", "L3", lead=True)
    w.aadm = mk_user(db, "AAdmin", "BRANCH_ADMIN", w.A); w.astaff = mk_user(db, "AStaff", "BRANCH_STAFF", w.A)
    w.badm = mk_user(db, "BAdmin", "BRANCH_ADMIN", w.B); w.bstaff = mk_user(db, "BStaff", "BRANCH_STAFF", w.B)
    w.rm = mk_user(db, "RMgr", "REGIONAL_MANAGER", region=r.id)
    db.commit()
    return w


def phone_ticket(db, w, user=None, **kw):
    from app.services import workflow as wf
    args = dict(source="phone_inbound", description="Parcel not delivered for 5 days", mobile="9876543210",
                name="Ravi", category_id=w.cat.id, consignment_no="SK123", pincode="400053",
                allow_duplicate=True, now=T0)
    args.update(kw)
    t = wf.create_ticket(db, user or w.l1, **args)
    db.commit()
    return t
