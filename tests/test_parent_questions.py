import pytest
from fastapi.testclient import TestClient
from app import main,staff,policies,conflicts,notifications,auth,parent_questions

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(main,"DB",str(tmp_path/"tracking.db"))
    monkeypatch.setenv("SCHOOL_ADMIN_KEY","test-key")
    monkeypatch.setattr(main,"rebuild_index",lambda:True)
    monkeypatch.setattr(main.rag,"search",lambda *args,**kwargs:[])
    monkeypatch.setattr(main.rag,"enabled",lambda:True)
    policies.configure(main.db,main.auth,main.extract_text,main.rebuild_index)
    conflicts.configure(main.db,main.auth,main.rebuild_index)
    notifications.configure(main.db,main.auth)
    auth.configure(main.db,main.auth)
    staff.configure(main.db,main.auth)
    parent_questions.configure(main.db)
    main.setup()
    return TestClient(main.app)

def parent(client,username):
    h={"X-Admin-Key":"test-key"}
    assert client.post("/api/auth/parents",headers=h,json={
        "username":username,"display_name":username,"password":"secure-demo-password-123"}).status_code==201
    r=client.post("/api/auth/login",json={
        "username":username,"password":"secure-demo-password-123"})
    return {"Authorization":"Bearer "+r.json()["access_token"]}

def test_parent_ownership_and_staff_resolution(client):
    a=parent(client,"parentone")
    b=parent(client,"parenttwo")
    q=client.post("/api/chat",headers=a,json={"question":"Is the special bus route running?"})
    assert q.status_code==200
    assert q.json()["needs_staff"] is True
    ticket=q.json()["escalation_id"]
    assert [x["id"] for x in client.get("/api/parent/questions",headers=a).json()]==[ticket]
    assert client.get("/api/parent/questions",headers=b).json()==[]
    assert client.get("/api/parent/questions").status_code==401
    assert client.patch(f"/api/staff/questions/{ticket}",headers={"X-Admin-Key":"test-key"},
        json={"status":"resolved","resolution":"School office confirmed the special route is running."}).status_code==200
    item=client.get("/api/parent/questions",headers=a).json()[0]
    assert item["status"]=="resolved"
    assert "special route" in item["resolution"]
    assert client.get("/api/parent/questions",headers=b).json()==[]

def test_anonymous_tickets_are_not_claimable(client):
    a=parent(client,"parentthree")
    q=client.post("/api/chat",json={"question":"Is the extra pickup available?"})
    assert q.json()["needs_staff"]
    assert client.get("/api/parent/questions",headers=a).json()==[]
