"""Sample data for demos/UAT only. Passwords are generated and printed once."""
import secrets
from datetime import timedelta
from app.models import User, Region, Branch, BranchPincode, Category
from app.security import hash_password, utcnow
from app.services import workflow as wf


def load_demo(db):
    if db.query(Branch).count(): print("Demo data skipped (branches already exist)"); return
    pw = secrets.token_urlsafe(9) + "7x"
    h = hash_password(pw)
    west, east = Region(name="West"), Region(name="East"); db.add_all([west, east]); db.flush()
    mum = Branch(code="MUM01", name="Mumbai Andheri", city="Mumbai", state="Maharashtra", region_id=west.id, status="live")
    kol = Branch(code="KOL01", name="Kolkata Salt Lake", city="Kolkata", state="West Bengal", region_id=east.id, status="live")
    db.add_all([mum, kol]); db.flush()
    db.add_all([BranchPincode(branch_id=mum.id, pincode="400053"), BranchPincode(branch_id=kol.id, pincode="700091")])
    def mk(name, role, branch=None, lead=False, region=None):
        u = User(name=name, email=f"{name.lower().replace(' ', '.')}@skyking.demo", role=role, branch_id=branch.id if branch else None,
                 region_id=region, status="active", is_team_lead=lead, password_hash=h); db.add(u); db.flush(); return u
    l1 = mk("Priya L1", "L1", lead=True); mk("Rahul L1", "L1"); l2 = mk("Neha L2", "L2", lead=True); l3 = mk("Vikram L3", "L3", lead=True)
    mk("Anil Mumbai Admin", "BRANCH_ADMIN", mum); mk("Sunita Mumbai Staff", "BRANCH_STAFF", mum)
    mk("Debu Kolkata Admin", "BRANCH_ADMIN", kol); mk("West Regional Manager", "REGIONAL_MANAGER", region=west.id)
    cat = db.query(Category).first()
    for i, (mob, d) in enumerate([("9830000001", "Parcel not delivered for a week"), ("9830000002", "Box arrived damaged"),
                                  ("9830000003", "Wrong person received the parcel")]):
        wf.create_ticket(db, l1, source="phone_inbound", description=d, mobile=mob, name=f"Customer {i + 1}",
                         category_id=cat.id, consignment_no=f"SKY{1000 + i}", pincode="400053", allow_duplicate=True)
    db.commit()
    print(f"Demo users (all @skyking.demo) share this password, shown once: {pw}")
