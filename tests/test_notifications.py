from datetime import date,timedelta
import pytest
from fastapi.testclient import TestClient
from app import main, policies, conflicts, notifications

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(main,"DB",str(tmp_path/"notifications.db"))
    monkeypatch.setenv("SCHOOL_ADMIN_KEY","test-key")
    monkeypatch.setattr(main,"rebuild_index",lambda:True)
    policies.configure(main.db,main.auth,main.extract_text,main.rebuild_index)
    conflicts.configure(main.db,main.auth,main.rebuild_index)
    notifications.configure(main.db,main.auth)
    main.setup()
    return TestClient(main.app)

def policy(client,key,effective):
    h={"X-Admin-Key":"test-key"}
    r=client.post("/api/policies",headers=h,
        data={"policy_key":key,"title":key,"effective_date":effective},
        files={"file":("policy.txt",b"Approved school policy for testing the parent notifications inbox.")})
    assert r.status_code==201
    pid=r.json()["id"]
    assert client.post(f"/api/policies/{pid}/review",headers=h,json={"approve":True}).status_code==200
    return pid

def test_opt_in_approved_effective_only_read_and_unsubscribe(client):
    token=client.post("/api/notifications/subscribe",json={"label":"Parent demo"}).json()["token"]
    h={"X-Notification-Token":token}
    assert client.get("/api/notifications").status_code==401
    assert client.get("/api/notifications",headers={"X-Notification-Token":"wrong"}).status_code==401
    past=policy(client,"library-updates",(date.today()-timedelta(days=1)).isoformat())
    future=policy(client,"bus-updates",(date.today()+timedelta(days=3)).isoformat())
    # Drafts must not appear.
    r=client.post("/api/policies",headers={"X-Admin-Key":"test-key"},
        data={"policy_key":"sports-updates","title":"sports-updates","effective_date":date.today().isoformat()},
        files={"file":("draft.txt",b"Draft school policy for sports activities and school grounds.")})
    assert r.status_code==201
    items=client.get("/api/notifications",headers=h).json()
    assert [x["policy_id"] for x in items]==[past]
    assert items[0]["is_read"]==0
    assert client.post(f"/api/notifications/{future}/read",headers=h).status_code==404
    assert client.post(f"/api/notifications/{past}/read",headers=h).json()["read"]
    assert client.get("/api/notifications",headers=h).json()[0]["is_read"]==1
    assert client.delete("/api/notifications/subscription",headers=h).json()["unsubscribed"]
    assert client.get("/api/notifications",headers=h).status_code==401

def test_admin_summary_protected(client):
    assert client.get("/api/notifications/admin/summary").status_code==401
    assert client.get("/api/notifications/admin/summary",headers={"X-Admin-Key":"test-key"}).json()["subscribers"]==0
