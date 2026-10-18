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
