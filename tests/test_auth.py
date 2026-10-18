from datetime import date
import pytest
from fastapi.testclient import TestClient
from app import main,auth,policies,conflicts,notifications

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(main,"DB",str(tmp_path/"auth.db"))
    monkeypatch.setenv("SCHOOL_ADMIN_KEY","test-key")
    monkeypatch.setattr(main,"rebuild_index",lambda:True)
    policies.configure(main.db,main.auth,main.extract_text,main.rebuild_index)
    conflicts.configure(main.db,main.auth,main.rebuild_index)
    notifications.configure(main.db,main.auth)
    auth.configure(main.db,main.auth)
    main.setup()
    return TestClient(main.app)

def create(client,username):
    return client.post("/api/auth/parents",headers={"X-Admin-Key":"test-key"},
        json={"username":username,"display_name":username,"password":"secure-demo-password-123"})

def login(client,username):
    r=client.post("/api/auth/login",json={"username":username,"password":"secure-demo-password-123"})
    assert r.status_code==200
    return {"Authorization":"Bearer "+r.json()["access_token"]}

def test_parent_accounts_are_admin_provisioned(client):
    assert client.post("/api/auth/parents",json={"username":"parent1","display_name":"Parent One","password":"secure-demo-password-123"}).status_code==401
    assert create(client,"parent1").status_code==201
    assert create(client,"parent1").status_code==409
    assert client.post("/api/auth/login",json={"username":"parent1","password":"incorrect"}).status_code==401
    h=login(client,"parent1")
    assert client.get("/api/auth/me",headers=h).json()["role"]=="parent"
    assert client.get("/api/auth/me").status_code==401
    assert client.post("/api/auth/logout",headers=h).status_code==200
    assert client.get("/api/auth/me",headers=h).status_code==401

def test_private_parent_read_receipts_and_disable(client):
    first=create(client,"parenta").json()["id"]
    create(client,"parentb")
    a=login(client,"parenta");b=login(client,"parentb")
    r=client.post("/api/policies",headers={"X-Admin-Key":"test-key"},
        data={"policy_key":"transport-updates","title":"Transport updates","effective_date":date.today().isoformat()},
        files={"file":("bus.txt",b"The school transport update is effective immediately for all routes.")})
    pid=r.json()["id"]
    assert client.post(f"/api/policies/{pid}/review",headers={"X-Admin-Key":"test-key"},json={"approve":True}).status_code==200
    assert client.get("/api/notifications/mine").status_code==401
    assert client.get("/api/notifications/mine",headers=a).json()[0]["is_read"]==0
    assert client.post(f"/api/notifications/mine/{pid}/read",headers=a).status_code==200
    assert client.get("/api/notifications/mine",headers=a).json()[0]["is_read"]==1
    assert client.get("/api/notifications/mine",headers=b).json()[0]["is_read"]==0
    assert client.post(f"/api/auth/parents/{first}/disable",headers={"X-Admin-Key":"test-key"}).status_code==200
    assert client.get("/api/auth/me",headers=a).status_code==401
    assert client.get("/api/auth/me",headers=b).status_code==200


def test_login_throttling(client):
    from app import auth
    auth._login_attempts.clear()
    for _ in range(5):
        assert client.post("/api/auth/login",json={"username":"blockedparent","password":"incorrect"}).status_code==401
    r=client.post("/api/auth/login",json={"username":"blockedparent","password":"incorrect"})
    assert r.status_code==429
    assert "Retry-After" in r.headers
    auth._login_attempts.clear()
