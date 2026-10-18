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

def test_authenticated_inbox_and_retired_anonymous_routes(client):
    h={"X-Admin-Key":"test-key"}
    assert client.post("/api/auth/parents",headers=h,json={"username":"noticesparent","display_name":"Demo Parent","password":"demo-secure-password-123"}).status_code==201
    token=client.post("/api/auth/login",json={"username":"noticesparent","password":"demo-secure-password-123"}).json()["access_token"]
    bearer={"Authorization":"Bearer "+token}
    past=policy(client,"library-updates",(date.today()-timedelta(days=1)).isoformat())
    future=policy(client,"bus-updates",(date.today()+timedelta(days=3)).isoformat())
    assert client.get("/api/notifications/mine").status_code==401
    assert [x["policy_id"] for x in client.get("/api/notifications/mine",headers=bearer).json()]==[past]
    assert client.post(f"/api/notifications/mine/{future}/read",headers=bearer).status_code==404
    assert client.post(f"/api/notifications/mine/{past}/read",headers=bearer).status_code==200
    assert client.get("/api/notifications/mine",headers=bearer).json()[0]["is_read"]==1
    assert client.post("/api/notifications/subscribe",json={"label":"legacy"}).status_code==404
    assert client.get("/api/notifications").status_code==404
    assert client.delete("/api/notifications/subscription").status_code==404

def test_admin_summary_protected(client):
    assert client.get("/api/notifications/admin/summary").status_code==401
    assert client.get("/api/notifications/admin/summary",headers={"X-Admin-Key":"test-key"}).json()["authenticated_parents"]==0
