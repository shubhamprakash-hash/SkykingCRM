from datetime import timedelta
import pytest
from app.enums import S
from app import models as m
from app.services import workflow as wf, sla
from app.services.errors import *
from .conftest import T0, phone_ticket


def scan(db, now):
    r = sla.scan(db, now); return r


def events(db, t):
    db.flush()
    return [e.event_type for e in db.query(m.TicketEvent).filter_by(ticket_id=t.id).order_by(m.TicketEvent.id)]


# ---------------------------------------------------------------- manual (phone) creation
def test_agent_creates_phone_ticket(db, w):
    t = phone_ticket(db, w, call_received_at=T0, caller_number="9876543210", call_reference="REC-77")
    assert t.number == "CRM-0000001" and t.status == S.L1_QUEUE and t.level == 1
    assert t.source == "phone_inbound" and t.call_reference == "REC-77"
    assert t.due_at == T0 + timedelta(hours=6)            # 10:00 -> 16:00 IST, same working day
    assert db.query(m.OutboundMessage).filter_by(ticket_id=t.id).count() == 1   # acknowledgement queued
    assert events(db, t) == ["created"]
    assert t.customer.mobile == "9876543210"


def test_required_fields_and_number_sequence(db, w):
    with pytest.raises(ValidationFailed): wf.create_ticket(db, w.l1, source="phone_inbound", description="x y z", mobile=None, category_id=w.cat.id)
    with pytest.raises(ValidationFailed): wf.create_ticket(db, w.l1, source="phone_inbound", description="x y z", mobile="9876543210")  # no category
    a, b = phone_ticket(db, w, consignment_no="A1"), phone_ticket(db, w, consignment_no="A2")
    assert (a.number, b.number) == ("CRM-0000001", "CRM-0000002")


def test_incomplete_flag_and_duplicate_warning(db, w):
    t = phone_ticket(db, w, consignment_no=None, pincode=None)
    assert t.incomplete
    t2 = phone_ticket(db, w, consignment_no="DUP1")
    with pytest.raises(DuplicateFound) as e:
        wf.create_ticket(db, w.l1, source="phone_inbound", description="same issue again", mobile="9876543210",
                         category_id=w.cat.id, consignment_no="DUP1", now=T0)
    assert e.value.extra["numbers"] == [t2.number]


def test_take_and_resolve_on_first_call(db, w):
    t = wf.create_ticket(db, w.l1, source="phone_inbound", description="Wrong address delivered", mobile="9000000001",
                         category_id=w.cat.id, mode="take", now=T0,
                         resolve={"action_taken": "Re-delivered", "outcome": "Customer satisfied"})
    db.commit()
    assert t.status == S.RESOLVED and t.resolved_on_first_call and t.owner_id == w.l1.id


def test_original_description_is_immutable(db, w):
    t = phone_ticket(db, w); wf.pick(db, t, w.l1, now=T0)
    with pytest.raises(ValidationFailed): wf.update_details(db, t, w.l1, now=T0, description="changed")
    wf.update_details(db, t, w.l1, now=T0, address="12 MG Road")
    assert "details_updated" in events(db, t)


# ---------------------------------------------------------------- pick / escalate / auto escalation
def test_pick_is_exclusive(db, w):
    t = phone_ticket(db, w)
    wf.pick(db, t, w.l1, now=T0)
    with pytest.raises(NotAllowed): wf.pick(db, t, w.l1b, now=T0)
    with pytest.raises(NotAllowed): wf.pick(db, phone_ticket(db, w, consignment_no="Z9"), w.l2, now=T0)   # wrong level


def test_manual_escalation_needs_reason_and_level(db, w):
    t = phone_ticket(db, w); wf.pick(db, t, w.l1, now=T0)
    with pytest.raises(ValidationFailed): wf.escalate(db, t, w.l1, "", now=T0)
    with pytest.raises(NotAllowed): wf.escalate(db, t, w.l2, "because", now=T0)
    wf.escalate(db, t, w.l1, "Needs branch investigation", now=T0)
    assert (t.status, t.level, t.owner_id) == (S.L2_QUEUE, 2, None)
    assert t.due_at == T0 + timedelta(hours=6)


def test_auto_escalation_after_six_working_hours_and_idempotent(db, w):
    t = phone_ticket(db, w)
    assert scan(db, T0 + timedelta(hours=5, minutes=59)).get("escalated") is None
    r = scan(db, T0 + timedelta(hours=6)); db.refresh(t)
    assert r["escalated"] == 1 and t.status == S.L2_QUEUE
    assert scan(db, T0 + timedelta(hours=6)).get("escalated") is None          # running twice never escalates twice
    ev = db.query(m.TicketEvent).filter_by(ticket_id=t.id, event_type="escalated").one()
    assert ev.trigger == "auto_sla" and ev.actor_type == "system"


def test_working_hours_clock_skips_nights(db, w):
    late = T0 + timedelta(hours=7)                      # Monday 17:00 IST
    t = phone_ticket(db, w, now=late)                   # 2h Monday + 4h Tuesday => Tuesday 13:00 IST
    assert t.due_at == late + timedelta(hours=20)       # 11:30 UTC Mon -> 07:30 UTC Tue + ... check below
    assert scan(db, late + timedelta(hours=10)).get("escalated") is None       # Monday 03:00 UTC night: nothing
    assert scan(db, late + timedelta(hours=20)).get("escalated") == 1


def test_critical_priority_has_shorter_threshold(db, w):
    t = phone_ticket(db, w, priority="critical")
    assert t.due_at == T0 + timedelta(hours=2)


def test_activity_resets_timer(db, w):
    t = phone_ticket(db, w); wf.pick(db, t, w.l1, now=T0)
    later = T0 + timedelta(hours=5)
    wf.post_message(db, w.l1, t, "note", "called customer", now=later); db.commit()
    assert scan(db, T0 + timedelta(hours=6)).get("escalated") is None
    assert scan(db, later + timedelta(hours=20)).get("escalated") == 1   # 4h Mon + 2h Tue (working time)


def test_warning_at_80_percent(db, w):
    t = phone_ticket(db, w); wf.pick(db, t, w.l1, now=T0)
    assert scan(db, T0 + timedelta(hours=4)).get("warnings") == 0
    assert scan(db, T0 + timedelta(hours=5)).get("warnings") == 1              # 5h > 80% of 6h
    assert scan(db, T0 + timedelta(hours=5, minutes=5)).get("warnings") == 0   # once only
    assert db.query(m.Notification).filter_by(user_id=w.l1.id, kind="warning").count() == 1


# ---------------------------------------------------------------- L2: branch / L3 paths
def to_l2(db, w, t, now=T0):
    wf.pick(db, t, w.l1, now=now); wf.escalate(db, t, w.l1, "needs L2", now=now); db.commit()
    wf.pick(db, t, w.l2, now=now); db.commit(); return t


def test_assign_to_branch_full_cycle(db, w):
    t = to_l2(db, w, phone_ticket(db, w))
    with pytest.raises(ValidationFailed): wf.assign_branch(db, t, w.l2, w.C.id, now=T0)                  # not live
    with pytest.raises(ValidationFailed): wf.assign_branch(db, t, w.l2, w.A.id, deadline_minutes=30, now=T0)  # below min
    wf.assign_branch(db, t, w.l2, w.A.id, deadline_minutes=240, now=T0); db.commit()
    assert t.status == S.ASSIGNED_BRANCH and t.due_at == T0 + timedelta(hours=4) and t.owner_id == w.l2.id
    wf.branch_ack(db, t, w.astaff, now=T0); wf.branch_action_taken(db, t, w.astaff, "Parcel located and redispatched", now=T0)
    assert t.status == S.ACTION_TAKEN
    wf.verify(db, t, w.l2, True, note="Customer confirmed delivery", now=T0)
    assert t.status == S.RESOLVED and t.resolved_level == 2
    wf.close(db, t, w.l2, now=T0)
    assert t.status == S.CLOSED
    assert {"assigned_branch", "branch_acknowledged", "action_taken", "verified_resolved", "closed"} <= set(events(db, t))


def test_incomplete_ticket_cannot_go_to_branch(db, w):
    t = to_l2(db, w, phone_ticket(db, w, consignment_no=None, pincode=None))
    with pytest.raises(ValidationFailed): wf.assign_branch(db, t, w.l2, w.A.id, now=T0)
    wf.update_details(db, t, w.l2, now=T0, consignment_no="C1", pincode="400053")
    wf.assign_branch(db, t, w.l2, w.A.id, now=T0)


def test_only_assigned_branch_can_act(db, w):
    t = to_l2(db, w, phone_ticket(db, w)); wf.assign_branch(db, t, w.l2, w.A.id, now=T0)
    with pytest.raises(NotAllowed): wf.branch_ack(db, t, w.bstaff, now=T0)
    with pytest.raises(NotAllowed): wf.branch_ack(db, t, w.l2, now=T0)
    with pytest.raises(NotAllowed): wf.resolve_ticket(db, t, w.astaff, action_taken="x", outcome="y", now=T0)


def test_branch_deadline_missed_escalates_to_l3(db, w):
    t = to_l2(db, w, phone_ticket(db, w)); wf.assign_branch(db, t, w.l2, w.A.id, deadline_minutes=120, now=T0); db.commit()
    assert scan(db, T0 + timedelta(hours=1, minutes=59)).get("branch_breach_escalated") is None
    assert scan(db, T0 + timedelta(hours=2)).get("branch_breach_escalated") == 1; db.refresh(t)
    assert (t.status, t.level, t.branch_id) == (S.L3_QUEUE, 3, w.A.id)       # branch keeps access to the thread
    ev = db.query(m.TicketEvent).filter_by(ticket_id=t.id, event_type="escalated").order_by(m.TicketEvent.id.desc()).first()
    assert ev.trigger == "branch_breach"
    assert db.query(m.Notification).filter_by(user_id=w.l3.id).count() >= 1


def test_branch_breach_can_be_set_to_alert_only(db, w):
    from app.services import settings_service as cfgs
    cfgs.set_cfg(db, {"branch_breach_action": "alert_l2"}); db.commit()
    t = to_l2(db, w, phone_ticket(db, w)); wf.assign_branch(db, t, w.l2, w.A.id, deadline_minutes=120, now=T0); db.commit()
    assert scan(db, T0 + timedelta(hours=2)).get("branch_alerted") == 1; db.refresh(t)
    assert t.status == S.ASSIGNED_BRANCH


def test_l2_escalates_directly_to_l3_with_branch(db, w):
    t = to_l2(db, w, phone_ticket(db, w)); wf.assign_branch(db, t, w.l2, w.A.id, now=T0)
    wf.escalate(db, t, w.l2, "Customer is a key account", now=T0)
    assert (t.status, t.level, t.branch_id) == (S.L3_QUEUE, 3, w.A.id)
    wf.post_message(db, w.astaff, t, "thread", "Parcel is in transit", now=T0)    # branch can still talk to HO


def test_branch_return_goes_to_l2(db, w):
    t = to_l2(db, w, phone_ticket(db, w)); wf.assign_branch(db, t, w.l2, w.A.id, now=T0)
    wf.branch_return(db, t, w.astaff, "Wrong branch, belongs to Kolkata", now=T0)
    assert (t.status, t.branch_id) == (S.L2_QUEUE, None)
    assert db.query(m.TicketBranch).filter_by(ticket_id=t.id, branch_id=w.A.id).one().active is False


def test_extend_deadline_limits(db, w):
    t = to_l2(db, w, phone_ticket(db, w)); wf.assign_branch(db, t, w.l2, w.A.id, deadline_minutes=120, now=T0)
    wf.extend_deadline(db, t, w.l2, 60, "in transit", now=T0); wf.extend_deadline(db, t, w.l2, 60, "still transit", now=T0)
    assert t.due_at == T0 + timedelta(hours=4)
    with pytest.raises(ValidationFailed): wf.extend_deadline(db, t, w.l2, 60, "third", now=T0)
    with pytest.raises(NotAllowed): wf.extend_deadline(db, t, w.l2, 60, "late", now=T0 + timedelta(hours=5))


def test_verify_rejection_returns_to_branch(db, w):
    t = to_l2(db, w, phone_ticket(db, w)); wf.assign_branch(db, t, w.l2, w.A.id, now=T0)
    wf.branch_action_taken(db, t, w.astaff, "Called the customer once", now=T0)
    wf.verify(db, t, w.l2, False, note="Customer says nobody called", now=T0)
    assert t.status == S.ASSIGNED_BRANCH


def test_l3_breach_alerts_repeat(db, w):
    t = to_l2(db, w, phone_ticket(db, w)); wf.escalate(db, t, w.l2, "senior review", now=T0); db.commit()
    assert scan(db, T0 + timedelta(hours=6)).get("l3_alert") == 1; db.refresh(t)
    assert t.status == S.L3_QUEUE
    assert scan(db, T0 + timedelta(hours=6, minutes=1)).get("l3_alert") is None
    assert scan(db, T0 + timedelta(hours=12)).get("l3_alert") == 1       # repeats every 6 hours


# ---------------------------------------------------------------- de-escalation
def to_l3(db, w, t):
    to_l2(db, w, t); wf.escalate(db, t, w.l2, "need L3", now=T0); db.commit()
    wf.pick(db, t, w.l3, now=T0); db.commit(); return t

NOTE = "Please contact the customer and collect the receiver phone number."


def test_deescalate_l3_to_l2_rules(db, w):
    t = to_l3(db, w, phone_ticket(db, w))
    with pytest.raises(ValidationFailed): wf.deescalate(db, t, w.l3, "bogus", NOTE, now=T0)
    with pytest.raises(ValidationFailed): wf.deescalate(db, t, w.l3, "escalated_too_early", "short", now=T0)
    with pytest.raises(NotAllowed): wf.deescalate(db, t, w.l2, "escalated_too_early", NOTE, now=T0)
    later = T0 + timedelta(hours=1)
    wf.deescalate(db, t, w.l3, "escalated_too_early", NOTE, now=later); db.commit()
    assert (t.status, t.level) == (S.L2_WORKING, 2) and t.owner_id == w.l2.id    # back to previous L2 owner
    assert t.due_at == later + timedelta(hours=6) and t.cooling and t.deescalation_count == 1
    ev = db.query(m.TicketEvent).filter_by(ticket_id=t.id, event_type="deescalated").one()
    assert ev.reason_code == "escalated_too_early" and ev.note == NOTE and ev.from_level == 3 and ev.to_level == 2


def test_cooling_rule_blocks_immediate_bounce_until_action(db, w):
    t = to_l3(db, w, phone_ticket(db, w)); wf.deescalate(db, t, w.l3, "other", NOTE, now=T0)
    with pytest.raises(NotAllowed): wf.escalate(db, t, w.l2, "back up again", now=T0)
    wf.post_message(db, w.l2, t, "note", "reviewing", now=T0)                    # receiving level logs an action
    assert t.cooling is False
    wf.escalate(db, t, w.l2, "still needs L3", now=T0)


def test_automatic_timer_still_works_while_cooling(db, w):
    t = to_l3(db, w, phone_ticket(db, w)); wf.deescalate(db, t, w.l3, "other", NOTE, now=T0); db.commit()
    assert scan(db, T0 + timedelta(hours=6)).get("escalated") == 1               # nothing can sit unattended


def test_deescalation_limit_needs_admin(db, w):
    t = to_l3(db, w, phone_ticket(db, w))
    for i in range(2):
        wf.deescalate(db, t, w.l3, "other", NOTE, now=T0)
        wf.post_message(db, w.l2, t, "note", "x", now=T0); wf.escalate(db, t, w.l2, "again", now=T0); wf.pick(db, t, w.l3, now=T0)
    with pytest.raises(NotAllowed): wf.deescalate(db, t, w.l3, "other", NOTE, now=T0)
    wf.deescalate(db, t, w.admin, "other", NOTE, now=T0)                        # admin may approve
    assert t.repeated_movement is True                                          # 4+ level changes flagged


def test_l2_to_l1_with_branch_requires_choice(db, w):
    t = to_l2(db, w, phone_ticket(db, w)); wf.assign_branch(db, t, w.l2, w.A.id, now=T0)
    with pytest.raises(ValidationFailed): wf.deescalate(db, t, w.l2, "more_information_needed", NOTE, now=T0)
    wf.deescalate(db, t, w.l2, "more_information_needed", NOTE, withdraw_branch=True, now=T0)
    assert (t.level, t.branch_id) == (1, None) and t.status == S.L1_WORKING        # previous L1 owner
    assert db.query(m.Notification).filter_by(user_id=w.aadm.id).count() >= 1


def test_deescalate_named_user_and_skip_rules(db, w):
    t = to_l3(db, w, phone_ticket(db, w))
    with pytest.raises(NotAllowed): wf.deescalate(db, t, w.l3, "other", NOTE, skip=True, now=T0)
    wf.deescalate(db, t, w.l3, "other", NOTE, target_user_id=w.l2b.id, now=T0)
    assert t.owner_id == w.l2b.id
    with pytest.raises(ValidationFailed): wf.deescalate(db, t, w.admin, "other", NOTE, target_user_id=w.l3.id, now=T0)  # wrong level
    wf.escalate(db, t, w.admin, "admin push", now=T0)
    wf.deescalate(db, t, w.admin, "other", NOTE, skip=True, now=T0)
    assert t.level == 1


def test_cannot_deescalate_terminal_or_draft(db, w):
    t = to_l2(db, w, phone_ticket(db, w)); wf.resolve_ticket(db, t, w.l2, action_taken="done", outcome="all fine", now=T0)
    with pytest.raises(NotAllowed): wf.deescalate(db, t, w.l2, "other", NOTE, now=T0)


# ---------------------------------------------------------------- the transition matrix (proof)
def test_every_status_pair_is_either_allowed_or_rejected(db, w):
    for a in S.ALL:
        for b in S.ALL:
            t = m.Ticket(number=f"X-{a}-{b}", source="other", description="d", status=a, level=S.LEVEL_OF.get(a, 2), priority="medium")
            allowed = b in wf.ALLOWED.get(a, set())
            if allowed:
                wf._move(db, t, b, T0)
                assert t.status == b
            else:
                with pytest.raises(InvalidTransition):
                    wf._move(db, t, b, T0)
                assert t.status == a                                     # nothing changed on rejection


def test_closed_is_never_directly_resolvable_and_cannot_skip(db, w):
    assert S.RESOLVED not in wf.ALLOWED[S.CLOSED] and S.CLOSED not in wf.ALLOWED[S.L1_QUEUE]
    assert S.L3_QUEUE not in wf.ALLOWED[S.L1_QUEUE] and S.L3_QUEUE not in wf.ALLOWED[S.L1_WORKING]   # L1 cannot jump to L3
    assert S.L1_QUEUE not in wf.ALLOWED[S.L3_QUEUE]                                                   # L3 cannot jump to L1


def test_admin_force_is_audited(db, w):
    t = phone_ticket(db, w)
    wf.admin_force(db, t, w.admin, S.L3_QUEUE, "Escalate on MD instruction", now=T0)
    assert t.level == 3
    assert db.query(m.TicketEvent).filter_by(ticket_id=t.id, event_type="admin_force").one().trigger == "admin_force"
    with pytest.raises(NotAllowed): wf.admin_force(db, t, w.l3, S.L1_QUEUE, "not admin", now=T0)
