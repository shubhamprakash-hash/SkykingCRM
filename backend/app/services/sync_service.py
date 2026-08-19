"""
Pulls tickets from MSG91, applies the eligibility rule, and upserts into
msg91_tickets + tickets. Uses msg91_ticket_id as the external identifier so
re-fetching an already-seen ticket UPDATES the existing row rather than
creating a duplicate (spec section 17).

Handles:
  - New eligible ticket -> creates Customer (if new) + Msg91Ticket + Ticket
    (status=AVAILABLE)
  - Existing ticket, still eligible -> updates msg91 mirror fields
    (last message, unread count, status) without touching CRM workflow
    fields (status/assignee/comments), which only change via user actions
  - Existing ticket, no longer eligible (e.g. reassigned to an individual
    agent, no longer to Support Team) -> flagged, does not disappear from
    CRM (audit trail must survive), but is excluded from "Available" views
    going forward. Logged to ticket_history.
"""
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.models import (
    Msg91Ticket, Ticket, Customer, TicketStatus, TicketHistory, EscalationLevel
)
from app.services import config_service
from app.services.msg91_client import Msg91Client


def _next_crm_code(db: Session) -> str:
    count = db.query(Ticket).count()
    return f"CRM-{count + 1:07d}"


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def upsert_msg91_ticket(db: Session, raw: dict) -> Msg91Ticket:
    external_id = raw["ticket_id"]
    row = db.query(Msg91Ticket).filter(Msg91Ticket.msg91_ticket_id == external_id).first()

    last_msg = (raw.get("last_message") or {}).get("message", {})
    last_msg_text = (last_msg.get("content") or {}).get("text")

    fields = dict(
        chat_id=raw.get("id"),
        channel=raw.get("channel"),
        client_id=raw.get("client_id"),
        uuid=raw.get("uuid"),
        origin=raw.get("origin"),
        inbox_id=(raw.get("inbox_ids") or [{}])[0].get("inbox_id"),
        customer_name=raw.get("customer_name"),
        customer_number=raw.get("customer_number"),
        assignee_id=str(raw.get("assignee_id")),
        assignee_type=raw.get("assignee_type"),
        widget_unread_count=raw.get("widget_unread_count", 0),
        cc_unread_count=raw.get("cc_unread_count", 0),
        last_message_by=raw.get("last_message_by"),
        last_message_snippet=last_msg_text,
        last_message_at=_parse_dt(last_msg.get("created_at")),
        msg91_created_at=_parse_dt(raw.get("created_at")),
        raw_payload=raw,
    )

    if row is None:
        row = Msg91Ticket(msg91_ticket_id=external_id, **fields)
        db.add(row)
        db.flush()
    else:
        for k, v in fields.items():
            setattr(row, k, v)

    return row


def get_or_create_customer(db: Session, raw: dict) -> Customer:
    uuid = raw.get("uuid")
    customer = db.query(Customer).filter(Customer.msg91_uuid == uuid).first()
    if customer:
        # keep name/number fresh
        customer.name = raw.get("customer_name") or customer.name
        customer.mobile_number = raw.get("customer_number") or customer.mobile_number
        return customer
    customer = Customer(
        name=raw.get("customer_name"),
        mobile_number=raw.get("customer_number"),
        msg91_uuid=uuid,
    )
    db.add(customer)
    db.flush()
    return customer


def sync_tickets(db: Session, pages: int = 3, per_page: int = 100) -> dict:
    """
    Fetches `pages` pages of tickets from MSG91, filters by the configured
    eligibility rule, and upserts. Returns a summary for logging/monitoring.
    """
    rule = config_service.get_eligibility_rule(db)
    client = Msg91Client()

    created, updated, skipped_ineligible = 0, 0, 0

    for page in range(1, pages + 1):
        data = client.get_tickets(page=page, per_page=per_page)
        channels = data.get("chat_channels", [])
        if not channels:
            break

        for raw in channels:
            if not config_service.is_eligible(raw, rule):
                skipped_ineligible += 1
                continue

            msg91_row = upsert_msg91_ticket(db, raw)
            existing_crm_ticket = db.query(Ticket).filter(Ticket.msg91_ticket_pk == msg91_row.id).first()

            if existing_crm_ticket is None:
                customer = get_or_create_customer(db, raw)
                crm_ticket = Ticket(
                    crm_code=_next_crm_code(db),
                    msg91_ticket_pk=msg91_row.id,
                    customer_id=customer.id,
                    status=TicketStatus.AVAILABLE,
                    escalation_level=EscalationLevel.L0,
                )
                db.add(crm_ticket)
                db.flush()
                db.add(TicketHistory(
                    ticket_id=crm_ticket.id,
                    action="msg91_ticket_received",
                    new_status=TicketStatus.AVAILABLE.value,
                    escalation_level=EscalationLevel.L0.value,
                    comment=f"Synced from MSG91 ticket #{raw['ticket_id']}",
                ))
                created += 1
            else:
                updated += 1

        db.commit()

    return {"created": created, "updated": updated, "skipped_ineligible": skipped_ineligible}
