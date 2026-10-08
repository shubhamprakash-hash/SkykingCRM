"""First-run setup:  python -m app.seed
Creates the super-admin from ADMIN_EMAIL / ADMIN_PASSWORD (there is no built-in default password),
default categories, and rule defaults. With --demo it also creates sample branches, users and complaints."""
import sys, secrets
from app.config import get_settings
from app.database import SessionLocal, Base, engine
from app.models import User, Category, Counter, Region, Branch, BranchPincode
from app.security import hash_password, check_password_policy

CATEGORIES = [("Delivery delay", "medium"), ("Not delivered / lost", "high"), ("Damaged consignment", "high"),
              ("Wrong delivery", "medium"), ("Billing / payment", "low"), ("Staff behaviour", "medium"), ("Other", "low")]


def main(demo=False):
    s = get_settings()
    Base.metadata.create_all(engine)
    db = SessionLocal()
    if not db.query(Counter).filter_by(name="ticket").first():
        db.add(Counter(name="ticket", value=0))
    for n, p in CATEGORIES:
        if not db.query(Category).filter_by(name=n).first(): db.add(Category(name=n, default_priority=p))
    if not db.query(User).filter_by(role="SUPER_ADMIN").first():
        if not s.ADMIN_EMAIL:
            raise SystemExit("Set ADMIN_EMAIL (and ADMIN_PASSWORD) in the environment to create the first admin.")
        pw = s.ADMIN_PASSWORD or secrets.token_urlsafe(12) + "9a"
        err = check_password_policy(pw)
        if err: raise SystemExit(err)
        db.add(User(name="Super Admin", email=s.ADMIN_EMAIL.lower(), role="SUPER_ADMIN", status="active", password_hash=hash_password(pw)))
        if not s.ADMIN_PASSWORD: print(f"Generated admin password (shown once): {pw}")
    db.commit()
    if demo:
        from app.demo import load_demo
        load_demo(db)
    db.close()
    print("Setup complete.")


if __name__ == "__main__":
    main(demo="--demo" in sys.argv)
