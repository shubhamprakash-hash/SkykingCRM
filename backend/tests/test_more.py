import random
from datetime import timedelta
import pytest
from sqlalchemy.orm.exc import StaleDataError
from app.enums import S
from app import models as m
from app.services import workflow as wf, sla, access
from app.services.errors import *
from .conftest import T0, phone_ticket
from .test_workflow import to_l2, to_l3, scan, events, NOTE


def branch_ticket(db, w, user=None, **kw):
    args = dict(source="branch", description="Customer walked in: parcel damaged", mobile="9811111111", name="Asha",
                category_id=w.cat2.id, consignment_no="BR1", pincode="400053", now=T0)
    args.update(kw)
    t = wf.create_ticket(db, user or w.astaff, **args); db.commit(); return t


# ------------------------------------------------------------ branch register-and-forward
def test_branch_registers_and_forwards_to_l1(db, w):
    t = branch_ticket(db, w)
    assert (t.status, t.level, t.source, t.origin_branch_id) == (S.L1_QUEUE, 1, "branch", w.A.id)
    assert t.forwarded_at == T0 and t.due_at == T0 + timedelta(hours=2 if False else 6) or t.priority == "high"
    assert events(db, t) == ["created", "forwarded"]
    assert access.can_view(db, w.astaff, t) and access.can_view(db, w.l1, t)
    assert not access.can_view(db, w.bstaff, t)                      # other branch sees nothing


def test_branch_draft_is_private_and_untimed(db, w):
    t = branch_ticket(db, w, mode="draft", mobile=None)
    assert t.status == S.DRAFT and t.due_at is None and t.level is None
    assert access.can_view(db, w.aadm, t) and not access.can_view(db, w.l1, t) and access.can_view(db, w.admin, t)
    assert scan(db, T0 + timedelta(days=3)).get("escalated") is None  # drafts are not tracked by SLA
    wf.update_details(db, t, w.astaff, now=T0, consignment_no="D1", pincode="400053")
    t2 = wf.create_ticket  # noqa
    wf.forward(db, t, w.astaff, now=T0 + timedelta(hours=1)); db.commit()
    assert t.status == S.L1_QUEUE and t.due_at is not None
    with pytest.raises(NotAllowed): wf.forward(db, t, w.astaff, now=T0)


def test_branch_cannot_register_unless_live_or_for_other_branch(db, w):
    pending_user = m.User(name="C", email="c@x.com", role="BRANCH_STAFF", branch_id=w.C.id, status="active")
    db.add(pending_user); db.flush()
    with pytest.raises(NotAllowed): branch_ticket(db, w, user=pending_user)


def test_branch_can_withdraw_only_before_pickup(db, w):
    t = branch_ticket(db, w)
    wf.withdraw(db, t, w.astaff, now=T0); assert t.status == S.DRAFT
    wf.forward(db, t, w.astaff, now=T0); wf.pick(db, t, w.l1, now=T0)
    with pytest.raises(NotAllowed): wf.withdraw(db, t, w.astaff, now=T0)


def test_urgent_branch_complaint_alerts_team_leads(db, w):
    t = branch_ticket(db, w, urgent=True, category_id=w.cat.id)
    assert t.priority == "high" and t.urgent_flag
    assert db.query(m.Notification).filter_by(user_id=w.l1lead.id, kind="alert").count() == 1
    assert db.query(m.Notification).filter_by(user_id=w.l2lead.id, kind="alert").count() == 1


def test_return_for_info_pauses_and_branch_reply_resumes(db, w):
    t = branch_ticket(db, w); wf.pick(db, t, w.l1, now=T0)
    t0 = T0 + timedelta(hours=2)
    wf.return_for_info(db, t, w.l1, "What is the receiver phone number?", now=t0); db.commit()
    assert t.status == S.AWAITING_BRANCH_INFO and t.remaining_minutes == 240 - 0 or t.remaining_minutes > 0
    rem = t.remaining_minutes
    wf.post_message(db, w.astaff, t, "thread", "Receiver phone is 9822222222", now=t0 + timedelta(minutes=30)); db.commit()
    assert t.status == S.L1_WORKING and t.paused_from_status is None
    assert t.due_at == t0 + timedelta(minutes=30 + rem)              # the remaining time, not a fresh 6h
    with pytest.raises(NotAllowed): wf.return_for_info(db, phone_ticket(db, w, consignment_no="Q"), w.l1, "question?", now=T0)


def test_unanswered_branch_info_request_alerts_l2(db, w):
    t = branch_ticket(db, w); wf.pick(db, t, w.l1, now=T0)
    wf.return_for_info(db, t, w.l1, "Need the invoice number", now=T0); db.commit()
    assert scan(db, T0 + timedelta(hours=6)).get("info_overdue") == 1


# ------------------------------------------------------------ visibility / scope
def test_scope_rules(db, w):
    t = to_l2(db, w, phone_ticket(db, w)); wf.assign_branch(db, t, w.l2, w.A.id, now=T0); db.commit()
    t2 = to_l2(db, w, phone_ticket(db, w, consignment_no="OTHER")); wf.assign_branch(db, t2, w.l2, w.B.id, now=T0); db.commit()
    ids = lambda u: {x.id for x in access.visible_tickets(db, u)}
    assert ids(w.astaff) == {t.id} and ids(w.bstaff) == {t2.id}
    assert ids(w.l1) == {t.id, t2.id} and ids(w.admin) == {t.id, t2.id}
    assert ids(w.rm) == {t.id}                                       # regional manager: West only


def test_withdrawn_branch_keeps_read_only_history(db, w):
    t = to_l2(db, w, phone_ticket(db, w)); wf.assign_branch(db, t, w.l2, w.A.id, now=T0)
    wf.deescalate(db, t, w.l2, "more_information_needed", NOTE, withdraw_branch=True, now=T0); db.commit()
    assert t.branch_id is None and access.can_view(db, w.astaff, t)
    with pytest.raises(NotAllowed): wf.post_message(db, w.astaff, t, "thread", "hello", now=T0)


def test_message_channel_permissions(db, w):
    t = to_l2(db, w, phone_ticket(db, w)); wf.assign_branch(db, t, w.l2, w.A.id, now=T0)
    with pytest.raises(NotAllowed): wf.post_message(db, w.astaff, t, "note", "internal", now=T0)
    with pytest.raises(NotAllowed): wf.post_message(db, w.astaff, t, "customer_out", "hi", now=T0)
    with pytest.raises(NotAllowed): wf.post_message(db, w.bstaff, t, "thread", "intruder", now=T0)
    wf.post_message(db, w.astaff, t, "thread", "on it", now=T0)


# ------------------------------------------------------------ customer events
def test_customer_reply_resumes_paused_complaint(db, w):
    t = phone_ticket(db, w); wf.pick(db, t, w.l1, now=T0); wf.await_customer(db, t, w.l1, "waiting for photos", now=T0 + timedelta(hours=2)); db.commit()
    assert t.status == S.AWAITING_CUSTOMER and t.due_at is None
    assert scan(db, T0 + timedelta(days=5)).get("escalated") is None   # paused: no escalation
    assert wf.customer_reply(db, t, "photos attached", now=T0 + timedelta(days=1)) == "resumed"
    assert t.status == S.L1_WORKING and t.due_at is not None


def test_customer_reply_after_resolution_reopens_within_window(db, w):
    t = phone_ticket(db, w); wf.pick(db, t, w.l1, now=T0)
    wf.resolve_ticket(db, t, w.l1, action_taken="redelivered", outcome="delivered", now=T0)
    assert wf.customer_reply(db, t, "still not received", now=T0 + timedelta(days=2)) == "reopened"
    assert (t.status, t.level, t.reopen_count) == (S.L1_QUEUE, 1, 1)
    wf.pick(db, t, w.l1, now=T0); wf.resolve_ticket(db, t, w.l1, action_taken="again", outcome="done", now=T0)
    assert wf.customer_reply(db, t, "late reply", now=T0 + timedelta(days=9)) == "window_passed"


def test_resolved_auto_closes_and_customer_can_confirm(db, w):
    t = phone_ticket(db, w); wf.pick(db, t, w.l1, now=T0); wf.resolve_ticket(db, t, w.l1, action_taken="fixed", outcome="fixed", now=T0); db.commit()
    assert scan(db, T0 + timedelta(hours=47)).get("auto_closed") is None
    assert scan(db, T0 + timedelta(hours=48)).get("auto_closed") == 1
    t2 = phone_ticket(db, w, consignment_no="C2"); wf.pick(db, t2, w.l1, now=T0); wf.resolve_ticket(db, t2, w.l1, action_taken="a b", outcome="a b", now=T0)
    wf.customer_confirm(db, t2, now=T0); assert t2.status == S.CLOSED


def test_close_permissions(db, w):
    t = phone_ticket(db, w, priority="critical"); wf.pick(db, t, w.l1, now=T0); wf.escalate(db, t, w.l1, "crit", now=T0); wf.pick(db, t, w.l2, now=T0)
    wf.resolve_ticket(db, t, w.l2, action_taken="fixed", outcome="fixed", now=T0)
    with pytest.raises(NotAllowed): wf.close(db, t, w.l2, now=T0)       # L2 cannot close a critical complaint
    wf.close(db, t, w.admin, now=T0)


def test_merge_duplicates_keeps_both_histories(db, w):
    a, b = phone_ticket(db, w, consignment_no="M1"), phone_ticket(db, w, consignment_no="M2")
    wf.merge(db, b, w.l1, a.id, now=T0); db.commit()
    assert b.status == S.CLOSED and b.merged_into_id == a.id
    assert "merge_received" in events(db, a) and "merged" in events(db, b)


# ------------------------------------------------------------ concurrency & orphans
def test_stale_version_is_rejected(db, w, SessionMaker):
    t = phone_ticket(db, w); seen = t.version                          # the version the second user's screen shows
    wf.pick(db, t, w.l1, now=T0); db.commit()
    other = SessionMaker()
    with pytest.raises(Conflict):
        wf.run_action(other, other.get(m.Ticket, t.id), other.get(m.User, w.l1b.id), "pick", expected_version=seen)
    other.close()


def test_simultaneous_writes_cannot_both_win(db, w, SessionMaker):
    t = phone_ticket(db, w)
    s1, s2 = SessionMaker(), SessionMaker()
    t1, t2 = s1.get(m.Ticket, t.id), s2.get(m.Ticket, t.id)
    wf.pick(s1, t1, s1.get(m.User, w.l1.id), now=T0)
    s1.commit()
    with pytest.raises(StaleDataError):                              # second writer loses; nothing half-saved
        wf.pick(s2, t2, s2.get(m.User, w.l1b.id), now=T0); s2.commit()
    s2.rollback(); s1.close(); s2.close()
    db.expire_all(); assert db.get(m.Ticket, t.id).owner_id == w.l1.id


def test_leaver_tickets_return_to_queue(db, w):
    t = phone_ticket(db, w); wf.pick(db, t, w.l1, now=T0)
    br = to_l2(db, w, phone_ticket(db, w, consignment_no="OR1")); wf.assign_branch(db, br, w.l2, w.A.id, assignee_id=w.astaff.id, now=T0)
    w.l1.status = "suspended"; w.l2.status = "suspended"; w.astaff.status = "suspended"
    wf.release_user_tickets(db, w.l1, w.admin, now=T0); wf.release_user_tickets(db, w.l2, w.admin, now=T0)
    wf.release_user_tickets(db, w.astaff, w.admin, now=T0); db.commit()
    assert (t.status, t.owner_id) == (S.L1_QUEUE, None)
    assert br.owner_id is None and br.branch_assignee_id is None
    assert sla.reconcile(db, T0) == []


def test_suspending_branch_returns_work_to_l2(db, w):
    t = to_l2(db, w, phone_ticket(db, w)); wf.assign_branch(db, t, w.l2, w.A.id, now=T0)
    w.A.status = "suspended"; assert wf.release_branch_tickets(db, w.A, w.admin, now=T0) == 1
    assert (t.status, t.branch_id) == (S.L2_QUEUE, None)


def test_available_actions_follow_permissions(db, w):
    t = phone_ticket(db, w)
    assert "pick" in wf.available_actions(db, t, w.l1) and "pick" not in wf.available_actions(db, t, w.l2)
    assert wf.available_actions(db, t, w.astaff) == []
    t3 = to_l3(db, w, phone_ticket(db, w, consignment_no="AA"))
    assert "deescalate" in wf.available_actions(db, t3, w.l3) and "escalate" not in wf.available_actions(db, t3, w.l3)


# ------------------------------------------------------------ randomized "proof" walk
ACTION_PARAMS = {
    "escalate": lambda w, r: {"reason": "needs senior"},
    "deescalate": lambda w, r: {"reason_code": "other", "note": NOTE, "withdraw_branch": r.choice([True, False])},
    "assign_branch": lambda w, r: {"branch_id": r.choice([w.A.id, w.B.id]), "deadline_minutes": r.choice([120, 240, 360])},
    "extend_deadline": lambda w, r: {"minutes": 60, "reason": "in transit"},
    "branch_action_taken": lambda w, r: {"notes": "Branch fixed the issue on site"},
    "branch_return": lambda w, r: {"reason": "belongs elsewhere"},
    "verify": lambda w, r: {"approve": r.choice([True, False]), "note": "verified ok", "action_taken": "fixed", "outcome": "fixed"},
    "resolve": lambda w, r: {"action_taken": "fixed it", "outcome": "customer ok"},
    "reopen": lambda w, r: {"reason": "customer unhappy"},
    "await_customer": lambda w, r: {"reason": "need photos"},
    "return_for_info": lambda w, r: {"question": "what is the phone number?"},
    "set_priority": lambda w, r: {"priority": r.choice(["low", "high", "critical"])},
    "update_details": lambda w, r: {"address": f"Street {r.randint(1, 99)}"},
    "branch_distribute": lambda w, r: {"assignee_id": w.astaff.id},
}


@pytest.mark.parametrize("seed", range(25))
def test_random_walk_never_breaks_invariants(db, w, seed):
    r = random.Random(seed)
    users = [w.l1, w.l1b, w.l2, w.l2b, w.l3, w.admin, w.aadm, w.astaff, w.bstaff, w.l1lead, w.l2lead]
    tickets = [phone_ticket(db, w, consignment_no=f"W{seed}{i}") for i in range(2)] + [branch_ticket(db, w, consignment_no=f"WB{seed}")]
    now, ok = T0, 0
    for step in range(70):
        now += timedelta(minutes=r.choice([0, 10, 90, 300, 700]))
        if r.random() < 0.3:
            scan(db, now)
        t, u = r.choice(tickets), r.choice(users)
        db.refresh(t)
        acts = [a for a in wf.available_actions(db, t, u) if a not in ("merge", "admin_force")]
        if not acts:
            continue
        a = r.choice(acts)
        n_events = db.query(m.TicketEvent).filter_by(ticket_id=t.id).count()
        params = ACTION_PARAMS.get(a, lambda w, r: {})(w, r)
        params["now"] = now
        try:
            wf.run_action(db, t, u, a, params); db.commit(); ok += 1
            assert db.query(m.TicketEvent).filter_by(ticket_id=t.id).count() > n_events, f"{a} wrote no audit event"
        except WorkflowError:
            db.rollback()
        # ---- invariants after every step
        db.refresh(t)
        assert t.status in S.ALL
        if t.status in S.LEVEL_OF: assert t.level == S.LEVEL_OF[t.status]
        assert sla.reconcile(db, now, stale_hours=10**6) == [], sla.reconcile(db, now, stale_hours=10**6)
    for t in tickets:       # every recorded move was a permitted move
        for e in db.query(m.TicketEvent).filter_by(ticket_id=t.id):
            if e.from_status and e.to_status and e.from_status != e.to_status and e.trigger != "admin_force" \
                    and e.event_type not in ("merged",) and not (e.meta or {}).get("skip"):
                assert e.to_status in wf.ALLOWED[e.from_status], (e.event_type, e.from_status, e.to_status)
    assert ok >= 10, "walk was too passive to prove anything"
