import pytest
from fastapi.testclient import TestClient
from app import main,staff,policies,conflicts,notifications,auth

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(main,"DB",str(tmp_path/"staff.db"))
    monkeypatch.setenv("SCHOOL_ADMIN_KEY","test-key")
    monkeypatch.setattr(main,"rebuild_index",lambda:True)
    policies.configure(main.db,main.auth,main.extract_text,main.rebuild_index)
    conflicts.configure(main.db,main.auth,main.rebuild_index)
    notifications.configure(main.db,main.auth)
    auth.configure(main.db,main.auth)
    staff.configure(main.db,main.auth)
    main.setup()
    return TestClient(main.app)

def test_staff_workflow_permissions_validation_and_history(client):
    with main.db() as c:
        id=c.execute("INSERT INTO escalations(question) VALUES(?)",
                     ("When is the next school bus inspection?",)).lastrowid
    path=f"/api/staff/questions/{id}"
    h={"X-Admin-Key":"test-key"}
    assert client.get("/api/staff/questions").status_code==401
    assert client.patch(path,json={"status":"resolved","resolution":"Verified"}).status_code==401
    assert client.patch(path,headers=h,json={"status":"assigned"}).status_code==422
    assert client.patch(path,headers=h,json={"status":"resolved"}).status_code==422
    assert client.patch(path,headers=h,json={"status":"assigned","assigned_to":"Office team"}).status_code==200
    assert client.get("/api/staff/questions?status=assigned",headers=h).json()[0]["assigned_to"]=="Office team"
    assert client.patch(path,headers=h,json={"status":"resolved","assigned_to":"Office team",
        "resolution":"The inspection is scheduled after confirmation from transport office."}).status_code==200
    assert client.patch(path,headers=h,json={"status":"open"}).status_code==409
    assert client.get("/api/staff/questions?status=resolved",headers=h).json()[0]["status"]=="resolved"
    assert [e["action"] for e in client.get(path+"/history",headers=h).json()]==["assigned","resolved"]
    assert client.get(path+"/history").status_code==401
    assert client.patch("/api/staff/questions/999",headers=h,json={"status":"open"}).status_code==404
