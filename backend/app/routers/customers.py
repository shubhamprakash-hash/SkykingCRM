from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import Customer, Ticket, User

router = APIRouter(prefix="/api/customers", tags=["customers"])


@router.get("")
def list_customers(search: str = "", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(Customer)
    if search:
        like = f"%{search}%"
        q = q.filter((Customer.name.ilike(like)) | (Customer.mobile_number.ilike(like)))
    customers = q.limit(50).all()
    return [{"id": c.id, "name": c.name, "mobile_number": c.mobile_number} for c in customers]


@router.get("/{customer_id}")
def get_customer(customer_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = db.query(Customer).options(joinedload(Customer.consignments)).filter(Customer.id == customer_id).first()
    if not c:
        raise HTTPException(404, "Customer not found")
    tickets = db.query(Ticket).filter(Ticket.customer_id == c.id).all()
    return {
        "id": c.id, "name": c.name, "mobile_number": c.mobile_number,
        "consignments": [
            {"id": cn.id, "consignment_number": cn.consignment_number, "address": cn.address}
            for cn in c.consignments
        ],
        "tickets": [
            {"id": t.id, "crm_code": t.crm_code, "status": t.status.value,
             "escalation_level": t.escalation_level.value}
            for t in tickets
        ],
    }
