from datetime import timedelta
import pytest
from app import models as m
from app.enums import S
from app.services import intake_msg91, intake_email, onboarding, workflow as wf
from app.services.errors import *
from .conftest import T0, phone_ticket, PW


# ------------------------------------------------------------ WhatsApp (MSG91, mock mode)
def test_msg91_sync_creates_complaints_once(db, w):
    r1 = intake_msg91.sync(db, now=T0)
    assert r1["created"] >= 1 and r1["skipped"] == 0
    n = db.query(m.Ticket).count()
    r2 = intake_msg91.sync(db, now=T0)
    assert r2["created"] == 0 and db.query(m.Ticket).count() == n         # de-duplicated on MSG91 ticket id
    t = db.query(m.Ticket).first()
    assert t.source == "whatsapp" and t.status == S.L1_QUEUE and t.customer.mobile and len(t.customer.mobile) == 10


def test_msg91_eligibility_rule(db, w):
    db.add(m.Setting(key="msg91_rule", value={"inbox_ids": [999999]})); db.commit()
    assert intake_msg91.sync(db, now=T0)["created"] == 0


# ------------------------------------------------------------ email
def raw(subject="Parcel delayed", body="My parcel SK99 has not arrived.", frm="Meena <meena@example.com>", mid="<a1@x>", extra=""):
    return (f"From: {frm}\r\nTo: complaints@skyking.in\r\nSubject: {subject}\r\nMessage-ID: {mid}\r\n{extra}"
            f"Content-Type: text/plain; charset=utf-8\r\n\r\n{body}\r\n").encode()


def test_email_creates_then_threads_replies(db, w):
    r = intake_email.process_raw_email(db, raw(), now=T0); db.commit()
    assert r["result"] == "created"
    t = db.query(m.Ticket).filter_by(number=r["ticket"]).one()
    assert t.source == "email" and t.customer.email == "meena@example.com"
    # reply via In-Reply-To header
    r2 = intake_email.process_raw_email(db, raw(subject="Re: Parcel delayed", mid="<a2@x>", body="Any update?",
                                                extra="In-Reply-To: <a1@x>\r\n"), now=T0)
    assert r2["result"].startswith("reply") and r2["ticket"] == t.number
    # reply that only carries the complaint number in the subject
    r3 = intake_email.process_raw_email(db, raw(subject=f"Complaint {t.number}", mid="<a3@x>", body="photo later"), now=T0)
    assert r3["ticket"] == t.number
    assert db.query(m.Ticket).count() == 1                                  # never a second complaint


def test_email_duplicates_and_automatic_mail_are_ignored(db, w):
    intake_email.process_raw_email(db, raw(), now=T0); db.commit()
    assert intake_email.process_raw_email(db, raw(), now=T0)["result"] == "duplicate"
    assert intake_email.process_raw_email(db, raw(mid="<b@x>", extra="Auto-Submitted: auto-replied\r\n"))["result"] == "ignored_automatic"
    assert intake_email.process_raw_email(db, raw(mid="<c@x>", frm="MAILER-DAEMON@x.com"))["result"] == "ignored_automatic"
    assert db.query(m.Ticket).count() == 1


def test_email_reply_resumes_waiting_complaint(db, w):
    r = intake_email.process_raw_email(db, raw(), now=T0); db.commit()
    t = db.query(m.Ticket).filter_by(number=r["ticket"]).one(); wf.pick(db, t, w.l1, now=T0)
    wf.await_customer(db, t, w.l1, "need invoice", now=T0); db.commit()
    out = intake_email.process_raw_email(db, raw(subject=f"Re: {t.number}", mid="<d@x>", body="invoice attached"), now=T0 + timedelta(hours=1))
    assert out["result"] == "reply_resumed" and t.status == S.L1_WORKING


# ------------------------------------------------------------ onboarding
def test_branch_admin_invites_staff_and_staff_joins_own_branch_only(db, w):
    inv, tok = onboarding.invite(db, w.aadm, name="New Staff", role="BRANCH_STAFF", mobile="9876500001"); db.commit()
    assert inv.branch_id == w.A.id and inv.status == "pending"
    with pytest.raises(ValidationFailed): onboarding.accept(db, tok, "short")
    u = onboarding.accept(db, tok, PW); db.commit()
    assert (u.role, u.branch_id, u.status) == ("BRANCH_STAFF", w.A.id, "active") and u.mobile == "9876500001"
    with pytest.raises(ValidationFailed): onboarding.accept(db, tok, PW)           # token is single use


def test_branch_cannot_create_head_office_or_other_branch_users(db, w):
    with pytest.raises(NotAllowed): onboarding.invite(db, w.aadm, name="X", role="L1", email="x@x.com")
    with pytest.raises(NotAllowed): onboarding.invite(db, w.aadm, name="X", role="SUPER_ADMIN", email="x@x.com")
    with pytest.raises(NotAllowed): onboarding.invite(db, w.astaff, name="X", role="BRANCH_STAFF", email="x@x.com")   # not an admin
    inv, _ = onboarding.invite(db, w.aadm, name="Y", role="BRANCH_STAFF", email="y@x.com", branch_id=w.B.id)
    assert inv.branch_id == w.A.id                                                  # branch_id param is ignored


def test_new_branch_admin_needs_head_office_approval(db, w):
    inv, tok = onboarding.invite(db, w.aadm, name="Second Admin", role="BRANCH_ADMIN", email="sa@x.com"); db.commit()
    assert inv.status == "awaiting_approval"
    with pytest.raises(ValidationFailed): onboarding.accept(db, tok, PW)
    with pytest.raises(NotAllowed): onboarding.approve(db, w.aadm, inv)
    onboarding.approve(db, w.admin, inv); db.commit()
    assert onboarding.accept(db, tok, PW).role == "BRANCH_ADMIN"


def test_invite_expiry_revoke_and_duplicates(db, w):
    inv, tok = onboarding.invite(db, w.admin, name="L1 New", role="L1", email="l1new@x.com", now=T0)
    with pytest.raises(ValidationFailed): onboarding.accept(db, tok, PW, now=T0 + timedelta(hours=73))
    inv2, tok2 = onboarding.invite(db, w.admin, name="L2 New", role="L2", email="l2new@x.com", now=T0)
    onboarding.revoke(db, w.admin, inv2)
    with pytest.raises(ValidationFailed): onboarding.accept(db, tok2, PW, now=T0)
    with pytest.raises(ValidationFailed): onboarding.invite(db, w.admin, name="Dup", role="L1", email="l1a@example.com")


def test_suspending_staff_releases_their_work(db, w):
    t = phone_ticket(db, w); wf.pick(db, t, w.l1, now=T0); db.commit()
    assert onboarding.set_user_status(db, w.admin, w.l1, "suspended", now=T0) == 1; db.commit()
    assert t.status == S.L1_QUEUE and w.l1.status == "suspended"
    with pytest.raises(NotAllowed): onboarding.set_user_status(db, w.aadm, w.bstaff, "suspended")    # other branch
    onboarding.set_user_status(db, w.aadm, w.astaff, "suspended")


def test_branch_csv_import(db, w):
    csv_text = ("code,name,city,state,region,address,contact_name,contact_email,contact_phone,pincodes\n"
                "PUN01,Pune Camp,Pune,MH,West,Camp Road,Ajay,a@x.com,9000000000,411001;411002\n"
                ",NoCode,,,,,,,,\n"
                "BLR01,Bengaluru,Bengaluru,KA,South,,,,,56001\n")
    r = onboarding.import_branches_csv(db, w.admin, csv_text); db.commit()
    assert r["created"] == 2 and len(r["errors"]) == 2                     # missing code + bad pincode
    assert db.query(m.BranchPincode).filter_by(branch_id=db.query(m.Branch).filter_by(code="PUN01").one().id).count() == 2
    with pytest.raises(NotAllowed): onboarding.import_branches_csv(db, w.aadm, csv_text)
