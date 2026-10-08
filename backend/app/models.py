from sqlalchemy import (Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON, Index,
                        UniqueConstraint)
from sqlalchemy.orm import relationship
from app.database import Base
from app.security import utcnow


class Region(Base):
    __tablename__ = "regions"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)


class Branch(Base):
    __tablename__ = "branches"
    id = Column(Integer, primary_key=True)
    code = Column(String(30), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    city = Column(String(100))
    state = Column(String(100))
    address = Column(Text)
    region_id = Column(Integer, ForeignKey("regions.id"))
    status = Column(String(20), default="pending", nullable=False)   # pending | live | suspended
    contact_name = Column(String(150))
    contact_email = Column(String(200))
    contact_phone = Column(String(30))
    created_at = Column(DateTime, default=utcnow)
    region = relationship("Region")
    pincodes = relationship("BranchPincode", cascade="all, delete-orphan")


class BranchPincode(Base):
    __tablename__ = "branch_pincodes"
    id = Column(Integer, primary_key=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    pincode = Column(String(10), nullable=False, index=True)
    __table_args__ = (UniqueConstraint("branch_id", "pincode"),)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False)
    email = Column(String(200), unique=True, index=True)
    mobile = Column(String(20), unique=True, index=True)
    password_hash = Column(String(200))
    role = Column(String(30), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"))
    region_id = Column(Integer, ForeignKey("regions.id"))
    status = Column(String(20), default="active", nullable=False)  # invited|pending_approval|active|suspended
    is_team_lead = Column(Boolean, default=False)
    failed_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime)
    last_login = Column(DateTime)
    created_at = Column(DateTime, default=utcnow)
    branch = relationship("Branch")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False)


class StaffInvitation(Base):
    __tablename__ = "staff_invitations"
    id = Column(Integer, primary_key=True)
    purpose = Column(String(10), default="invite")                  # invite | reset
    branch_id = Column(Integer, ForeignKey("branches.id"))
    name = Column(String(150))
    email = Column(String(200))
    mobile = Column(String(20))
    role = Column(String(30))
    user_id = Column(Integer, ForeignKey("users.id"))                # for reset
    token_hash = Column(String(64), unique=True)
    expires_at = Column(DateTime)
    status = Column(String(20), default="pending")  # pending|awaiting_approval|accepted|revoked
    invited_by = Column(Integer, ForeignKey("users.id"))
    approved_by = Column(Integer, ForeignKey("users.id"))
    accepted_user_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=utcnow)


class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    name = Column(String(200))
    mobile = Column(String(20), index=True)
    email = Column(String(200), index=True)
    created_at = Column(DateTime, default=utcnow)


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    default_priority = Column(String(10), default="medium")
    active = Column(Boolean, default=True)


class Counter(Base):
    __tablename__ = "counters"
    name = Column(String(50), primary_key=True)
    value = Column(Integer, default=0, nullable=False)


class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(Integer, primary_key=True)
    number = Column(String(20), unique=True, nullable=False, index=True)
    source = Column(String(20), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), index=True)
    category_id = Column(Integer, ForeignKey("categories.id"))
    subject = Column(String(300))
    description = Column(Text, nullable=False)             # immutable after creation
    priority = Column(String(10), default="medium", nullable=False)
    urgent_flag = Column(Boolean, default=False)
    status = Column(String(30), nullable=False, index=True)
    level = Column(Integer)                                # 1..3 (None for DRAFT)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), index=True)        # assigned branch
    branch_assignee_id = Column(Integer, ForeignKey("users.id"))
    origin_branch_id = Column(Integer, ForeignKey("branches.id"), index=True)  # branch that registered it
    created_by = Column(Integer, ForeignKey("users.id"))
    registered_by = Column(Integer, ForeignKey("users.id"))
    # consignment / contact details
    consignment_no = Column(String(60), index=True)
    receiver_name = Column(String(200))
    receiver_mobile = Column(String(20))
    address = Column(Text)
    pincode = Column(String(10))
    preferred_contact = Column(String(30))
    preferred_language = Column(String(30))
    # phone-call details
    caller_number = Column(String(20))
    call_received_at = Column(DateTime)
    call_reference = Column(String(100))
    incomplete = Column(Boolean, default=False)
    # timers
    created_at = Column(DateTime, default=utcnow, nullable=False)
    forwarded_at = Column(DateTime)
    level_entered_at = Column(DateTime)
    last_activity_at = Column(DateTime)
    due_at = Column(DateTime, index=True)
    warned_at = Column(DateTime)
    remaining_minutes = Column(Integer)                    # stored while paused
    paused_from_status = Column(String(30))
    branch_deadline_minutes = Column(Integer)
    extension_count = Column(Integer, default=0)
    # movement control
    cooling = Column(Boolean, default=False)
    escalation_count = Column(Integer, default=0)
    deescalation_count = Column(Integer, default=0)
    moves_count = Column(Integer, default=0)
    repeated_movement = Column(Boolean, default=False)
    prev_owner_by_level = Column(JSON, default=dict)
    # resolution
    resolved_at = Column(DateTime)
    resolved_level = Column(Integer)
    closed_at = Column(DateTime)
    reopen_count = Column(Integer, default=0)
    resolution_action = Column(Text)
    resolution_outcome = Column(Text)
    root_cause = Column(Text)
    resolved_on_first_call = Column(Boolean, default=False)
    merged_into_id = Column(Integer, ForeignKey("tickets.id"))
    version = Column(Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version}

    customer = relationship("Customer")
    branch = relationship("Branch", foreign_keys=[branch_id])
    origin_branch = relationship("Branch", foreign_keys=[origin_branch_id])
    owner = relationship("User", foreign_keys=[owner_id])
    category = relationship("Category")


class TicketEvent(Base):
    """Append-only audit trail. Never updated or deleted by application code."""
    __tablename__ = "ticket_events"
    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False, index=True)
    at = Column(DateTime, default=utcnow, nullable=False)
    actor_id = Column(Integer, ForeignKey("users.id"))
    actor_type = Column(String(10), default="user")        # user | system | customer
    event_type = Column(String(40), nullable=False)
    from_status = Column(String(30))
    to_status = Column(String(30))
    from_level = Column(Integer)
    to_level = Column(Integer)
    trigger = Column(String(20))       # manual|auto_sla|admin_force|branch_breach|l2_direct|deescalate|system
    reason_code = Column(String(50))
    reason = Column(Text)
    note = Column(Text)
    meta = Column(JSON)
    actor = relationship("User")


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), index=True)     # helpdesk channel
    channel = Column(String(15), nullable=False)    # thread | note | customer_out | customer_in | helpdesk
    author_id = Column(Integer, ForeignKey("users.id"))
    author_type = Column(String(10), default="user")
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    deleted = Column(Boolean, default=False)
    author = relationship("User")


class MessageRead(Base):
    __tablename__ = "message_reads"
    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    read_at = Column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("message_id", "user_id"),)


class Attachment(Base):
    __tablename__ = "attachments"
    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), index=True)
    message_id = Column(Integer, ForeignKey("messages.id"))
    filename = Column(String(255))
    content_type = Column(String(100))
    size = Column(Integer)
    storage_path = Column(String(500))
    uploaded_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=utcnow)
    scan_status = Column(String(15), default="pending")   # pending|clean|infected (hook for a scanner)


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"))
    kind = Column(String(30))
    text = Column(Text)
    created_at = Column(DateTime, default=utcnow)
    read = Column(Boolean, default=False)


class OutboundMessage(Base):
    """Outbox for customer-facing WhatsApp / SMS / email. A worker delivers these."""
    __tablename__ = "outbound_messages"
    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"))
    channel = Column(String(15))      # whatsapp | sms | email
    to = Column(String(200))
    body = Column(Text)
    status = Column(String(15), default="queued")   # queued | sent | failed
    attempts = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)
    sent_at = Column(DateTime)


class ExternalRef(Base):
    __tablename__ = "external_refs"
    id = Column(Integer, primary_key=True)
    source = Column(String(20), nullable=False)
    external_id = Column(String(200), nullable=False)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    marker = Column(String(100))
    __table_args__ = (UniqueConstraint("source", "external_id"),)


class EmailMessage(Base):
    __tablename__ = "email_messages"
    id = Column(Integer, primary_key=True)
    message_id = Column(String(300), unique=True, nullable=False)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), index=True)
    direction = Column(String(5), default="in")
    from_addr = Column(String(200))
    subject = Column(String(500))
    received_at = Column(DateTime, default=utcnow)


class SLAPolicy(Base):
    __tablename__ = "sla_policies"
    id = Column(Integer, primary_key=True)
    level = Column(Integer, nullable=False)
    priority = Column(String(10), nullable=False)
    minutes = Column(Integer, nullable=False)
    __table_args__ = (UniqueConstraint("level", "priority"),)


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String(50), primary_key=True)
    value = Column(JSON)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    at = Column(DateTime, default=utcnow)
    actor_id = Column(Integer)
    action = Column(String(60))
    detail = Column(JSON)


class TicketBranch(Base):
    """Every branch that has ever been assigned a ticket (keeps read-only access after withdrawal)."""
    __tablename__ = "ticket_branches"
    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False, index=True)
    active = Column(Boolean, default=True)
    assigned_at = Column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("ticket_id", "branch_id"),)
