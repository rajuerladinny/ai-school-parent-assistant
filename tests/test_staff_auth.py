from fastapi.testclient import TestClient
from app import main


def test_school_staff_cannot_read_other_school_questions(tmp_path,monkeypatch):
    monkeypatch.setattr(main,"DB",str(tmp_path/"staff.db"))
    monkeypatch.setenv("SCHOOL_ADMIN_KEY","test-key")
    main.setup()
    client=TestClient(main.app)
    with main.db() as c:
        c.execute("INSERT INTO schools(id,slug,name) VALUES(2,'staff-test','Staff Test School')")
        c.execute("INSERT INTO escalations(question,school_id) VALUES('School one question',1)")
        c.execute("INSERT INTO escalations(question,school_id) VALUES('School two question',2)")
    admin={"X-Admin-Key":"test-key"}
    for school in (1,2):
        r=client.post("/api/staff-auth/accounts",headers=admin,json={
            "username":f"staff{school}","display_name":"Demo Staff",
            "password":"long-password-for-test","school_id":school,"role":"staff"})
        assert r.status_code==201,r.text
    r=client.post("/api/staff-auth/login",json={"username":"staff2","password":"long-password-for-test"})
    assert r.status_code==200
    token=r.json()["access_token"]
    h={"Authorization":"Bearer "+token}
    assert client.get("/api/staff-auth/me",headers=h).json()["school_id"]==2
    questions=client.get("/api/staff/mine/questions",headers=h).json()
    assert len(questions)==1 and questions[0]["question"]=="School two question"
    other=client.get("/api/escalations",headers=admin).json()[0]["id"]
    assert client.patch(f"/api/staff/mine/questions/{other}",headers=h,
        json={"status":"resolved","resolution":"Not allowed"}).status_code==404
    assert client.post("/api/staff-auth/logout",headers=h).status_code==200
    assert client.get("/api/staff-auth/me",headers=h).status_code==401


def test_inactive_school_cannot_issue_staff_session(tmp_path,monkeypatch):
    monkeypatch.setattr(main,"DB",str(tmp_path/"inactive-staff.db"))
    monkeypatch.setenv("SCHOOL_ADMIN_KEY","test-key")
    main.setup()
    client=TestClient(main.app)
    created=client.post("/api/staff-auth/accounts",headers={"X-Admin-Key":"test-key"},
        json={"username":"inactive_staff","display_name":"Inactive Staff",
              "password":"long-password-for-test","school_id":1,"role":"staff"})
    assert created.status_code==201,created.text
    with main.db() as db:
        db.execute("UPDATE schools SET active=FALSE WHERE id=1")
    login=client.post("/api/staff-auth/login",json={
        "username":"inactive_staff","password":"long-password-for-test"})
    assert login.status_code==401

def test_school_deactivation_permanently_revokes_staff_session(tmp_path,monkeypatch):
    monkeypatch.setattr(main,"DB",str(tmp_path/"staff-revoke.db"))
    monkeypatch.setenv("SCHOOL_ADMIN_KEY","test-key")
    main.setup()
    client=TestClient(main.app)
    created=client.post("/api/staff-auth/accounts",headers={"X-Admin-Key":"test-key"},
        json={"username":"revoke_staff","display_name":"Revoked Staff",
              "password":"long-password-for-test","school_id":1,"role":"staff"})
    assert created.status_code==201
    response=client.post("/api/staff-auth/login",json={
        "username":"revoke_staff","password":"long-password-for-test"})
    assert response.status_code==200
    headers={"Authorization":"Bearer "+response.json()["access_token"]}
    assert client.get("/api/staff-auth/me",headers=headers).status_code==200
    with main.db() as db:
        db.execute("UPDATE schools SET active=FALSE WHERE id=1")
        db.execute("UPDATE schools SET active=TRUE WHERE id=1")
    assert client.get("/api/staff-auth/me",headers=headers).status_code==401
