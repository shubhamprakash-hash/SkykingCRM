"""
SkyKing CRM - relational schema.

Design notes:
- msg91_tickets / msg91_messages hold the RAW synced data from MSG91 (source
  of truth mirror). tickets is the CRM's own workflow record, linked 1:1 to
  msg91_tickets via msg91_ticket_id (external id, unique, used for upsert so
  re-fetching never creates duplicates -- see services/sync_service.py).
- customers <-> consignments is 1:many (a customer can have many
  consignments); consignments <-> tickets is 1:many (a ticket references at
  most one consignment at a time, but a consignment can be referenced by
  multiple tickets over its life).
- ticket_history is the append-only audit trail. Every state-changing action
  (pick, comment, escalate, resolve, close, reassign) writes exactly one row
  here and is never mutated afterward.
- escalations models the L1->L2->L3 chain as one row per hop so the chain
  (who held it, when, why) is queryable without re-deriving it from history.
"""
import enum
from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Boolean, DateTime, ForeignKey,
    Enum, UniqueConstraint, Index, JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RoleName(str, enum.Enum):
    ADMIN = "admin"
    SUPPORT = "support"       # initial handler / L0
    L1 = "l1"
    L2 = "l2"
    L3 = "l3"


class TicketStatus(str, enum.Enum):
    AVAILABLE = "available"
    PICKED = "picked"
    UNDER_REVIEW = "under_review"
    ESCALATED_L1 = "escalated_l1"
    ESCALATED_L2 = "escalated_l2"
    ESCALATED_L3 = "escalated_l3"
    RESOLVED = "resolved"
    CLOSED = "closed"


class EscalationLevel(str, enum.Enum):
    L0 = "l0"   # initial support handler
    L1 = "l1"
    L2 = "l2"
    L3 = "l3"


class Priority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MessageSender(str, enum.Enum):
    CUSTOMER = "customer"
    BOT = "bot"
    AGENT = "agent"
    SYSTEM = "system"


# ---------------------------------------------------------------------------
# Users / Roles
# ---------------------------------------------------------------------------

class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True)
    name = Column(Enum(RoleName), unique=True, nullable=False)
    description = Column(String(255))

    users = relationship("User", back_populates="role")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    role = relationship("Role", back_populates="users")


# ---------------------------------------------------------------------------
# System configuration (business rules, editable at runtime by Admin)
# ---------------------------------------------------------------------------

class SystemConfig(Base):
    """
    Key/value store for business rules such as:
      whatsapp_inbox_id, support_team_id, origin, assignee_type
    so these are NEVER hardcoded in application logic (spec section 21).
    """
    __tablename__ = "system_config"
    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(String(255), nullable=False)
    description = Column(String(255))
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# ---------------------------------------------------------------------------
# Customers / Consignments
# ---------------------------------------------------------------------------

class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    name = Column(String(255))
    mobile_number = Column(String(32), index=True)
    email = Column(String(255), nullable=True)
    msg91_uuid = Column(String(64), unique=True, nullable=True, index=True)  # MSG91 client uuid
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_customer_mobile", "mobile_number"),)

    consignments = relationship("Consignment", back_populates="customer")
    tickets = relationship("Ticket", back_populates="customer")


class Consignment(Base):
    __tablename__ = "consignments"
    id = Column(Integer, primary_key=True)
    consignment_number = Column(String(64), index=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    receiver_name = Column(String(255))
    receiver_mobile = Column(String(32))
    address = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("consignment_number", "customer_id", name="uq_consignment_customer"),
    )

    customer = relationship("Customer", back_populates="consignments")
    tickets = relationship("Ticket", back_populates="consignment")


# ---------------------------------------------------------------------------
# MSG91 raw mirror tables
# ---------------------------------------------------------------------------

class Msg91Ticket(Base):
    """Raw mirror of an MSG91 Hello ticket. Upserted by external ticket_id."""
    __tablename__ = "msg91_tickets"
    id = Column(Integer, primary_key=True)
    msg91_ticket_id = Column(BigInteger, unique=True, nullable=False, index=True)
    chat_id = Column(BigInteger, index=True)
    channel = Column(String(255))
    client_id = Column(String(64), index=True)
    uuid = Column(String(64), index=True)
    origin = Column(String(32))
    inbox_id = Column(Integer)
    customer_name = Column(String(255))
    customer_number = Column(String(32))
    assignee_id = Column(String(32))
    assignee_type = Column(String(32))
    status_raw = Column(String(32))         # msg91's own state (open/closed etc)
    widget_unread_count = Column(Integer, default=0)
    cc_unread_count = Column(Integer, default=0)
    last_message_by = Column(String(32))
    last_message_snippet = Column(Text)
    last_message_at = Column(DateTime(timezone=True))
    msg91_created_at = Column(DateTime(timezone=True))
    raw_payload = Column(JSON)              # full raw JSON, for forward-compat
    synced_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    ticket = relationship("Ticket", back_populates="msg91_ticket", uselist=False)
    messages = relationship("Msg91Message", back_populates="msg91_ticket")


class Msg91Message(Base):
    """Individual WhatsApp conversation messages pulled from MSG91's message API."""
    __tablename__ = "msg91_messages"
    id = Column(Integer, primary_key=True)
    msg91_ticket_id = Column(Integer, ForeignKey("msg91_tickets.id"), nullable=False)
    msg91_message_id = Column(String(128), unique=True, index=True)
    sender = Column(Enum(MessageSender), nullable=False)
    message_type = Column(String(32))
    content_text = Column(Text)
    raw_payload = Column(JSON)
    sent_at = Column(DateTime(timezone=True))

    msg91_ticket = relationship("Msg91Ticket", back_populates="messages")


# ---------------------------------------------------------------------------
# CRM Ticket (the workflow record)
# ---------------------------------------------------------------------------

class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(Integer, primary_key=True)
    crm_code = Column(String(32), unique=True, index=True)   # e.g. CRM-0000125
    msg91_ticket_pk = Column(Integer, ForeignKey("msg91_tickets.id"), unique=True, nullable=False)

    customer_id = Column(Integer, ForeignKey("customers.id"))
    consignment_id = Column(Integer, ForeignKey("consignments.id"), nullable=True)

    issue_summary = Column(Text)
    comment_note = Column(Text)

    status = Column(Enum(TicketStatus), default=TicketStatus.AVAILABLE, nullable=False, index=True)
    escalation_level = Column(Enum(EscalationLevel), default=EscalationLevel.L0, nullable=False, index=True)
    priority = Column(Enum(Priority), default=Priority.MEDIUM, nullable=False, index=True)

    assigned_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)

    msg91_ticket = relationship("Msg91Ticket", back_populates="ticket")
    customer = relationship("Customer", back_populates="tickets")
    consignment = relationship("Consignment", back_populates="tickets")
    assigned_user = relationship("User")
    comments = relationship("TicketComment", back_populates="ticket", order_by="TicketComment.created_at")
    history = relationship("TicketHistory", back_populates="ticket", order_by="TicketHistory.created_at")
    escalations = relationship("Escalation", back_populates="ticket", order_by="Escalation.created_at")


class TicketAssignment(Base):
    """Records every claim/pick/reassign event (kept distinct from history for fast 'current owner' queries)."""
    __tablename__ = "ticket_assignments"
    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action = Column(String(32))   # picked, reassigned, released
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    ticket = relationship("Ticket")
    user = relationship("User")


class TicketComment(Base):
    __tablename__ = "ticket_comments"
    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    escalation_level = Column(Enum(EscalationLevel), nullable=False)
    comment = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    ticket = relationship("Ticket", back_populates="comments")
    user = relationship("User")


class Escalation(Base):
    """One row per hop in the L0->L1->L2->L3 chain."""
    __tablename__ = "escalations"
    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False, index=True)
    from_level = Column(Enum(EscalationLevel), nullable=False)
    to_level = Column(Enum(EscalationLevel), nullable=False)
    from_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    to_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reason = Column(Text)
    forced_by_admin = Column(Boolean, default=False)  # true if a level was skipped by Admin override
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    ticket = relationship("Ticket", back_populates="escalations")


class TicketHistory(Base):
    """Append-only audit trail. Every state-changing action writes one row here."""
    __tablename__ = "ticket_history"
    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False, index=True)
    action = Column(String(64), nullable=False)
    previous_status = Column(String(32))
    new_status = Column(String(32))
    previous_assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    new_assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    escalation_level = Column(String(16))
    comment = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    ticket = relationship("Ticket", back_populates="history")
    user = relationship("User", foreign_keys=[user_id])
