from fastapi import APIRouter, Depends, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import current_user, require_roles
from app.enums import Role
from app.models import Branch, BranchPincode, Region, User, Ticket
from app.services import onboarding, workflow as wf
from app.services.errors import NotFound, ValidationFailed

router = APIRouter(prefix="/api", tags=["branches"])
ADMIN = require_roles(*Role.ADMIN)


def branch_out(b, db=None):
    return {"id": b.id, "code": b.code, "name": b.name, "city": b.city, "state": b.state, "address": b.address,
            "region": b.region.name if b.region else None, "region_id": b.region_id, "status": b.status,
            "contact_name": b.contact_name, "contact_email": b.contact_email, "contact_phone": b.contact_phone,
            "pincodes": sorted(p.pincode for p in b.pincodes)}


@router.get("/regions")
def regions(db: Session = Depends(get_db), u: User = Depends(current_user)):
    return [{"id": r.id, "name": r.name} for r in db.query(Region).order_by(Region.name)]


class RegionBody(BaseModel):
    name: str


@router.post("/regions", status_code=201)
def add_region(body: RegionBody, db: Session = Depends(get_db), u: User = Depends(ADMIN)):
    r = Region(name=body.name.strip()); db.add(r); db.commit(); return {"id": r.id, "name": r.name}


@router.get("/branches")
def branches(db: Session = Depends(get_db), u: User = Depends(current_user)):
    q = db.query(Branch)
    if u.role in Role.BRANCH: q = q.filter(Branch.id == u.branch_id)
    elif u.role == Role.REGIONAL_MANAGER: q = q.filter(Branch.region_id == u.region_id)
    return [branch_out(b) for b in q.order_by(Branch.name)]


class BranchBody(BaseModel):
    code: str
    name: str
    city: str | None = None
    state: str | None = None
    address: str | None = None
    region_id: int | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    pincodes: list[str] = []


@router.post("/branches", status_code=201)
def add_branch(body: BranchBody, db: Session = Depends(get_db), u: User = Depends(ADMIN)):
    code = body.code.strip().upper()
    if db.query(Branch).filter_by(code=code).first(): raise ValidationFailed("Branch code already exists")
    b = Branch(**{**body.model_dump(exclude={"pincodes", "code"}), "code": code}, status="pending")
    db.add(b); db.flush()
    for p in set(body.pincodes):
        if not (p.isdigit() and len(p) == 6): raise ValidationFailed(f"Invalid pincode {p}")
        db.add(BranchPincode(branch_id=b.id, pincode=p))
    onboarding.audit(db, u, "branch_created", {"branch": code}); db.commit(); db.refresh(b)
    return branch_out(b)


class BranchPatch(BaseModel):
    name: str | None = None
    city: str | None = None
    state: str | None = None
    address: str | None = None
    region_id: int | None = None
    status: str | None = None          # pending | live | suspended
    pincodes: list[str] | None = None


@router.patch("/branches/{bid}")
def patch_branch(bid: int, body: BranchPatch, db: Session = Depends(get_db), u: User = Depends(ADMIN)):
    b = db.get(Branch, bid)
    if not b: raise NotFound("Branch not found")
    d = body.model_dump(exclude_unset=True)
    pcs = d.pop("pincodes", None)
    st = d.pop("status", None)
    for k, v in d.items(): setattr(b, k, v)
    released = 0
    if st:
        if st not in ("pending", "live", "suspended"): raise ValidationFailed("invalid status")
        if st == "live" and not db.query(User).filter(User.branch_id == b.id, User.role == Role.BRANCH_ADMIN, User.status == "active").first():
            raise ValidationFailed("A branch needs an active Branch Admin before it can go live")
        b.status = st
        if st == "suspended": released = wf.release_branch_tickets(db, b, u)
        onboarding.audit(db, u, f"branch_{st}", {"branch": b.code, "released": released})
    if pcs is not None:
        db.query(BranchPincode).filter_by(branch_id=b.id).delete()
        for p in set(pcs):
            if not (p.isdigit() and len(p) == 6): raise ValidationFailed(f"Invalid pincode {p}")
            db.add(BranchPincode(branch_id=b.id, pincode=p))
    db.commit(); db.refresh(b)
    return {**branch_out(b), "tickets_returned": released}


@router.post("/branches/import")
async def import_csv(file: UploadFile = File(...), db: Session = Depends(get_db), u: User = Depends(ADMIN)):
    text = (await file.read()).decode("utf-8-sig")
    r = onboarding.import_branches_csv(db, u, text); db.commit(); return r
