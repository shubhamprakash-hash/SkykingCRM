"""
Run once after first deploy:  python -m app.seed
Creates the 5 roles, one Admin login, and imports the mock MSG91 ticket
data so the CRM already has tickets to work with -- nothing further to
click or sync.
"""
from app.core.database import SessionLocal, Base, engine
from app.core.security import hash_password
from app.models.models import Role, User, RoleName
from app.services.sync_service import sync_tickets

Base.metadata.create_all(bind=engine)
db = SessionLocal()

for role_name in RoleName:
    if not db.query(Role).filter(Role.name == role_name).first():
        db.add(Role(name=role_name, description=role_name.value.upper()))
db.commit()

admin_role = db.query(Role).filter(Role.name == RoleName.ADMIN).first()
if not db.query(User).filter(User.email == "admin@skyking.co").first():
    db.add(User(
        name="Admin",
        email="admin@skyking.co",
        hashed_password=hash_password("ChangeMe123!"),
        role_id=admin_role.id,
    ))
    db.commit()
    print("Created admin@skyking.co / ChangeMe123!  -- change this password immediately")
else:
    print("Admin already exists")

result = sync_tickets(db)
print(f"Imported tickets: {result}")

db.close()
