import io
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db
from app import models as m
from .conftest import PW, T0
from .test_workflow import NOTE


@pytest.fixture()
def client(SessionMaker, w, db):
    def _get_db():
        s = SessionMaker()
        try: yield s
        finally: s.close()
    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def login(client, email, pw=PW):
    r = client.post("/api/auth/login", json={"username": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}, r.json()


def H(client, name): return login(client, f"{name.lower()}@example.com")[0]


def new(client, h, **kw):
    body = dict(source="phone_inbound", description="Parcel not delivered", mobile="9876500000", category_id=1,
                consignment_no="API1", pincode="400053", allow_duplicate=True); body.update(kw)
    r = client.post("/api/tickets", json=body, headers=h); assert r.status_code == 201, r.text; return r.json()


def act(client, h, tid, action, version=None, **params):
    return client.post(f"/api/tickets/{tid}/actions", json={"action": action, "version": version, "params": params}, headers=h)


# ------------------------------------------------------------ auth
def test_login_lockout_refresh_rotation_and_logout(client, w):
    assert client.post("/api/auth/login", json={"username": "l1a@example.com", "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "nobody@example.com", "password": PW}).status_code == 401   # same answer
    for _ in range(5): client.post("/api/auth/login", json={"username": "l1b@example.com", "password": "bad"})
    assert client.post("/api/auth/login", json={"username": "l1b@example.com", "password": PW}).status_code == 423      # locked
    h, data = login(client, "l1a@example.com")
    assert client.get("/api/auth/me", headers=h).json()["role"] == "L1"
    r1 = client.post("/api/auth/refresh", json={"refresh_token": data["refresh_token"]}); assert r1.status_code == 200
    assert client.post("/api/auth/refresh", json={"refresh_token": data["refresh_token"]}).status_code == 401           # one-time use
    client.post("/api/auth/logout", json={"refresh_token": r1.json()["refresh_token"]})
    assert client.post("/api/auth/refresh", json={"refresh_token": r1.json()["refresh_token"]}).status_code == 401
    assert client.get("/api/tickets").status_code == 401
    assert client.get("/api/tickets", headers={"Authorization": "Bearer junk"}).status_code == 401


# ------------------------------------------------------------ phone creation + workflow over HTTP
def test_agent_creates_phone_ticket_and_it_works_end_to_end(client, w):
    l1, l2, l3 = H(client, "L1a"), H(client, "L2a"), H(client, "L3a")
    t = new(client, l1, call_reference="REC-1", caller_number="9876500000")
    assert t["status"] == "L1_QUEUE" and "pick" in t["actions"] and t["number"].startswith("CRM-")
    t = act(client, l1, t["id"], "pick", t["version"]).json(); assert t["status"] == "L1_WORKING"
    t = act(client, l1, t["id"], "escalate", t["version"], reason="Needs branch check").json(); assert t["level"] == 2
    assert act(client, l1, t["id"], "pick").status_code == 403                                       # L1 cannot pick at L2
    t = act(client, l2, t["id"], "pick").json()
    t = act(client, l2, t["id"], "assign_branch", branch_id=1 if False else w.A.id, deadline_minutes=240).json()
    assert t["status"] == "ASSIGNED_BRANCH" and t["branch"] == "Mumbai Andheri"
    br = H(client, "AStaff")
    assert act(client, br, t["id"], "branch_ack").json()["status"] == "BRANCH_ACK"
    r = client.post(f"/api/tickets/{t['id']}/messages", json={"channel": "thread", "body": "Located the parcel"}, headers=br); assert r.status_code == 201
    t = act(client, l2, t["id"], "escalate", reason="Key account").json(); assert t["level"] == 3
    t = act(client, l3, t["id"], "pick").json()
    t = act(client, l3, t["id"], "deescalate", reason_code="escalated_too_early", note=NOTE).json()
    assert t["level"] == 2 and t["cooling"] is True
    d = client.get(f"/api/tickets/{t['id']}", headers=l1).json()
    kinds = [e["type"] for e in d["events"]]
    assert kinds.count("escalated") == 2 and "deescalated" in kinds and "assigned_branch" in kinds
    assert any(e["reason_code"] == "escalated_too_early" for e in d["events"])


def test_validation_and_duplicate_errors_over_http(client, w):
    l1 = H(client, "L1a")
    r = client.post("/api/tickets", json={"source": "phone_inbound", "description": "no phone", "category_id": 1}, headers=l1)
    assert r.status_code == 422
    new(client, l1, consignment_no="DUPX", allow_duplicate=False)
    r = client.post("/api/tickets", json={"source": "phone_inbound", "description": "again again", "mobile": "9876500000",
                                          "category_id": 1, "consignment_no": "DUPX"}, headers=l1)
    assert r.status_code == 409 and r.json()["numbers"]
    chk = client.post("/api/tickets/check-duplicate", json={"mobile": "9876500000", "consignment_no": "DUPX"}, headers=l1).json()
    assert len(chk["duplicates"]) == 1


def test_stale_version_gives_409(client, w):
    l1 = H(client, "L1a"); t = new(client, l1)
    assert act(client, l1, t["id"], "pick", t["version"]).status_code == 200
    assert act(client, H(client, "L1b"), t["id"], "pick", t["version"]).status_code == 409


# ------------------------------------------------------------ branch scoping over HTTP
def test_branch_isolation(client, w):
    a, b, l1 = H(client, "AStaff"), H(client, "BStaff"), H(client, "L1a")
    ta = new(client, a, source="branch", description="Walk-in damaged parcel", mobile="9811000000", category_id=1)
    assert ta["status"] == "L1_QUEUE" and ta["origin_branch"] == "Mumbai Andheri"
    assert client.get(f"/api/tickets/{ta['id']}", headers=b).status_code == 404                  # no information leak
    assert client.get("/api/tickets", headers=b).json()["total"] == 0
    assert client.get("/api/tickets", headers=a).json()["total"] == 1
    assert client.get(f"/api/tickets/{ta['id']}", headers=l1).status_code == 200
    d = client.get(f"/api/tickets/{ta['id']}", headers=a).json()
    assert all(msg["channel"] == "thread" for msg in d["messages"])
    assert client.post(f"/api/tickets/{ta['id']}/messages", json={"channel": "note", "body": "x"}, headers=a).status_code == 403
    assert client.get("/api/reports/export.csv", headers=a).status_code == 403
    assert client.get("/api/users", headers=a).status_code == 403
    assert client.get("/api/branches", headers=b).json()[0]["code"] == "KOL01"


def test_branch_draft_then_forward_then_withdraw(client, w):
    a, l1 = H(client, "AStaff"), H(client, "L1a")
    t = new(client, a, description="Customer phoned the branch", mobile=None, category_id=None, mode="draft")
    assert t["status"] == "DRAFT" and "forward" in t["actions"]
    assert client.get("/api/tickets", headers=l1).json()["total"] == 0
    r = act(client, a, t["id"], "update_details", mobile=None) if False else None
    t = act(client, a, t["id"], "forward").json(); assert t["status"] == "L1_QUEUE"
    assert "withdraw" in t["actions"]
    assert act(client, a, t["id"], "withdraw").json()["status"] == "DRAFT"


# ------------------------------------------------------------ helpdesk, attachments, notifications, reports
def test_helpdesk_attachments_notifications_reports(client, w, tmp_path):
    a, l1, adm = H(client, "AStaff"), H(client, "L1a"), H(client, "Admin")
    assert client.post("/api/helpdesk", json={"body": "Our printer is down, how do we log complaints?"}, headers=a).status_code == 201
    msgs = client.get(f"/api/helpdesk?branch_id={w.A.id}", headers=l1).json(); assert len(msgs) == 1
    assert client.post("/api/helpdesk", json={"body": "Use the mobile app", "branch_id": w.A.id}, headers=l1).status_code == 201
    assert len(client.get("/api/helpdesk", headers=a).json()) == 2
    assert client.get("/api/helpdesk", headers=H(client, "BStaff")).json() == []
    t = new(client, l1)
    up = client.post(f"/api/tickets/{t['id']}/attachments", files={"file": ("photo.jpg", io.BytesIO(b"\xff\xd8data"), "image/jpeg")}, headers=l1)
    assert up.status_code == 201
    assert client.post(f"/api/tickets/{t['id']}/attachments", files={"file": ("virus.exe", io.BytesIO(b"MZ"), "application/octet-stream")}, headers=l1).status_code == 422
    assert client.get(f"/api/attachments/{up.json()['id']}", headers=l1).status_code == 200
    assert client.get(f"/api/attachments/{up.json()['id']}", headers=H(client, "BStaff")).status_code == 404
    n = client.get("/api/notifications", headers=a).json(); assert n["unread"] >= 0
    dash = client.get("/api/reports/dashboard", headers=adm).json()
    assert dash["open"] == 1 and dash["by_source"]["phone_inbound"] == 1 and "branch_league" in dash
    assert "number,created_at_utc" in client.get("/api/reports/export.csv", headers=adm).text


# ------------------------------------------------------------ onboarding over HTTP
def test_branch_admin_onboards_staff_through_the_api(client, w):
    adm = H(client, "AAdmin")
    r = client.post("/api/invitations", json={"name": "Kiran", "role": "BRANCH_STAFF", "mobile": "9899999999"}, headers=adm)
    assert r.status_code == 201; link = r.json()["invite_link"]; token = link.split("token=")[1]
    info = client.get(f"/api/auth/invite-info?token={token}").json(); assert info["branch"] == "Mumbai Andheri"
    assert client.post("/api/auth/accept-invite", json={"token": token, "password": "weak"}).status_code == 422
    assert client.post("/api/auth/accept-invite", json={"token": token, "password": "Strong-pass-77"}).status_code == 200
    h, data = login(client, "9899999999", "Strong-pass-77")
    assert data["user"]["branch_id"] == w.A.id and data["user"]["role"] == "BRANCH_STAFF"
    assert client.post("/api/invitations", json={"name": "Bad", "role": "L2", "email": "b@x.com"}, headers=adm).status_code == 403
    users = client.get("/api/users", headers=adm).json(); assert all(u["branch_id"] == w.A.id for u in users)


def test_admin_branch_management_and_csv(client, w):
    adm = H(client, "Admin")
    r = client.post("/api/branches", json={"code": "pun01", "name": "Pune", "pincodes": ["411001"]}, headers=adm); assert r.status_code == 201
    bid = r.json()["id"]
    assert client.patch(f"/api/branches/{bid}", json={"status": "live"}, headers=adm).status_code == 422       # needs a branch admin
    inv = client.post("/api/invitations", json={"name": "Pune Admin", "role": "BRANCH_ADMIN", "email": "pune@x.com", "branch_id": bid}, headers=adm).json()
    client.post("/api/auth/accept-invite", json={"token": inv["invite_link"].split("token=")[1], "password": "Strong-pass-77"})
    assert client.patch(f"/api/branches/{bid}", json={"status": "live"}, headers=adm).json()["status"] == "live"
    csv_text = "code,name,pincodes\nNAG01,Nagpur,440001\n"
    r = client.post("/api/branches/import", files={"file": ("b.csv", io.BytesIO(csv_text.encode()), "text/csv")}, headers=adm)
    assert r.json()["created"] == 1
    assert client.post("/api/branches", json={"code": "X", "name": "X"}, headers=H(client, "L1a")).status_code == 403
    assert client.get("/api/settings", headers=adm).json()["rules"]["default_minutes"] == 360
    assert client.put("/api/settings/rules", json={"branch_deadline_default": 480}, headers=adm).status_code == 200
    assert client.put("/api/settings/rules", json={"bogus": 1}, headers=adm).status_code == 422
    assert client.get("/api/settings", headers=H(client, "L2a")).status_code == 403
    assert any(a["action"] == "rules_changed" for a in client.get("/api/audit", headers=adm).json())


def test_webhooks_need_the_secret(client, w):
    raw = b"From: x@y.com\r\nSubject: Late parcel\r\nMessage-ID: <w1@x>\r\n\r\nParcel late"
    assert client.post("/api/intake/email", content=raw).status_code == 401
    r = client.post("/api/intake/email", content=raw, headers={"X-Webhook-Secret": "hook-secret"}); assert r.json()["result"] == "created"
    assert client.post("/api/intake/msg91/webhook", json={}, headers={"X-Webhook-Secret": "nope"}).status_code == 401
