from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    role: str

    class Config:
        from_attributes = True


class TicketListItem(BaseModel):
    id: int
    crm_code: str
    msg91_ticket_id: int
    customer_name: Optional[str]
    customer_number: Optional[str]
    created_at: datetime
    last_message_snippet: Optional[str]
    widget_unread_count: int
    assignee_type: Optional[str]
    status: str
    escalation_level: str
    priority: str
    assigned_user_name: Optional[str]
    updated_at: datetime

    class Config:
        from_attributes = True


class ResolutionDetailsUpdate(BaseModel):
    customer_name: Optional[str] = None
    mobile_number: Optional[str] = None
    consignment_number: Optional[str] = None
    address: Optional[str] = None
    issue_summary: Optional[str] = None
    comment_note: Optional[str] = None


class CommentIn(BaseModel):
    comment: str


class EscalateIn(BaseModel):
    reason: str
    force_level: Optional[str] = None  # admin-only skip target, e.g. "l3"


class ResolveIn(BaseModel):
    resolution_note: Optional[str] = None


class ReassignIn(BaseModel):
    new_user_id: int


class TicketDetail(BaseModel):
    id: int
    crm_code: str
    status: str
    escalation_level: str
    priority: str
    issue_summary: Optional[str]
    comment_note: Optional[str]
    customer: Optional[dict]
    consignment: Optional[dict]
    comments: List[dict]
    history: List[dict]
    msg91_last_message: Optional[str]

    class Config:
        from_attributes = True
