"""Actual FastAPI HTTP requests backed by a disposable PostgreSQL database.

The test temporarily patches the startup readiness gate, never changes the
production configuration gate. This isolates SQL/API compatibility from release approval.
"""
import os
import uuid
from urllib.parse import urlsplit,urlunsplit
import pytest


def test_fastapi_postgres_health_and_school_scoped_read(monkeypatch):
    dsn=os.getenv("TEST_POSTGRES_URL")
    if not dsn:pytest.skip("Requires TEST_POSTGRES_URL")
    import psycopg
    from fastapi.testclient import TestClient
    from app import main,database_config
    from scripts.postgres_bootstrap import initialize_empty
    parts=urlsplit(dsn)
    name="school_api_"+uuid.uuid4().hex[:12]
    admin=urlunsplit((parts.scheme,parts.netloc,"/postgres",parts.query,parts.fragment))
    target=urlunsplit((parts.scheme,parts.netloc,"/"+name,parts.query,parts.fragment))
    with psycopg.connect(admin,autocommit=True) as root:
        root.execute(f'CREATE DATABASE "{name}"')
    try:
        initialize_empty(target)
        with psycopg.connect(target) as c:
            c.execute("INSERT INTO schools(id,slug,name) VALUES(1,'demo','Demo School')")
            c.execute("INSERT INTO knowledge(school_id,topic,answer,source) VALUES(1,'Timings','9 AM','Handbook')")
        monkeypatch.setenv("SCHOOL_DATABASE_BACKEND","postgres")
        monkeypatch.setenv("SCHOOL_POSTGRES_DSN",target)
        monkeypatch.setenv("SCHOOL_ADMIN_KEY","test-key-for-integration")
        monkeypatch.setattr(database_config,"validate_configuration",lambda:"postgres")
        monkeypatch.setattr(main,"rebuild_index",lambda:False)
        with TestClient(main.app) as client:
            health=client.get("/api/health")
            assert health.status_code==200
            response=client.get("/api/knowledge",headers={"x-admin-key":"test-key-for-integration"})
            assert response.status_code==200,response.text
            assert len(response.json())==1
            assert response.json()[0]["topic"]=="Timings"
            headers={"x-admin-key":"test-key-for-integration"}
            created=client.post("/api/knowledge",headers=headers,json={"topic":"Transport","answer":"Bus routes are available","source":"Transport office"})
            assert created.status_code==201,created.text
            item_id=created.json()["id"]
            assert any(x["id"]==item_id for x in client.get("/api/knowledge",headers=headers).json())
            deleted=client.delete(f"/api/knowledge/{item_id}",headers=headers)
            assert deleted.status_code==200,deleted.text
            assert all(x["id"]!=item_id for x in client.get("/api/knowledge",headers=headers).json())
            escalations=client.get("/api/escalations",headers=headers)
            assert escalations.status_code==200,escalations.text
            policy=client.get("/api/policies/active")
            assert policy.status_code==200,policy.text
            doc=client.post("/api/documents",headers=headers,
                data={"title":"School Transport"},files={"file":("transport.txt",b"School transport routes operate every weekday morning and evening.","text/plain")})
            assert doc.status_code==201,doc.text
            doc_id=doc.json()["id"]
            assert any(x["id"]==doc_id for x in client.get("/api/documents",headers=headers).json())
            assert client.delete(f"/api/documents/{doc_id}",headers=headers).status_code==200
            assert all(x["id"]!=doc_id for x in client.get("/api/documents",headers=headers).json())
            policy_upload=client.post("/api/policies",headers=headers,
                data={"policy_key":"uniform","title":"Uniform Rules","effective_date":"2026-01-01"},
                files={"file":("uniform.txt",b"Students should wear the prescribed uniform on every school day.","text/plain")})
            assert policy_upload.status_code==201,policy_upload.text
            policy_id=policy_upload.json()["id"]
            assert any(x["id"]==policy_id for x in client.get("/api/policies",headers=headers).json())
            review=client.post(f"/api/policies/{policy_id}/review",headers=headers,json={"approve":True})
            assert review.status_code==200,review.text
            assert review.json()["status"]=="approved"
            assert any(x["title"]=="Uniform Rules" for x in client.get("/api/policies/active").json())
            staff=client.get("/api/staff/mine/questions")
            assert staff.status_code==401,staff.text
            parent=client.post("/api/auth/parents",headers=headers,json={
                "username":"pgparent","display_name":"Postgres Parent",
                "password":"secure-parent-pass-123","school_id":1})
            assert parent.status_code==201,parent.text
            parent_login=client.post("/api/auth/login",json={
                "username":"pgparent","password":"secure-parent-pass-123"})
            assert parent_login.status_code==200,parent_login.text
            parent_headers={"authorization":"Bearer "+parent_login.json()["access_token"]}
            parent_me=client.get("/api/auth/me",headers=parent_headers)
            assert parent_me.status_code==200,parent_me.text
            assert parent_me.json()["school_id"]==1
            assert client.post("/api/auth/logout",headers=parent_headers).status_code==200
            assert client.get("/api/auth/me",headers=parent_headers).status_code==401
            staff_account=client.post("/api/staff-auth/accounts",headers=headers,json={
                "username":"pgstaff","display_name":"Postgres Staff",
                "password":"secure-staff-pass-123","school_id":1,"role":"staff"})
            assert staff_account.status_code==201,staff_account.text
            staff_login=client.post("/api/staff-auth/login",json={
                "username":"pgstaff","password":"secure-staff-pass-123"})
            assert staff_login.status_code==200,staff_login.text
            staff_headers={"authorization":"Bearer "+staff_login.json()["access_token"]}
            assert client.get("/api/staff-auth/me",headers=staff_headers).status_code==200
            assert client.get("/api/staff/mine/questions",headers=staff_headers).status_code==200
            with psycopg.connect(target) as seeded:
                seeded.execute("INSERT INTO escalations(school_id,question) VALUES(1,'Where is the bus?')")
            mine=client.get("/api/staff/mine/questions",headers=staff_headers)
            assert mine.status_code==200,mine.text
            assert len(mine.json())==1
            question_id=mine.json()[0]["id"]
            assignment=client.patch(f"/api/staff/mine/questions/{question_id}",headers=staff_headers,json={
                "status":"assigned","assigned_to":"pgstaff"})
            assert assignment.status_code==200,assignment.text
            resolution=client.patch(f"/api/staff/mine/questions/{question_id}",headers=staff_headers,json={
                "status":"resolved","resolution":"Bus information sent"})
            assert resolution.status_code==200,resolution.text
            history=client.get(f"/api/staff/questions/{question_id}/history",headers=headers)
            assert history.status_code==200,history.text
            assert [event["action"] for event in history.json()]==["assigned","resolved"]
            with psycopg.connect(target) as seeded:
                seeded.execute("INSERT INTO schools(id,slug,name) VALUES(2,'other','Other School')")
                seeded.execute("INSERT INTO escalations(school_id,question) VALUES(2,'Private other-school question')")
                seeded.execute("INSERT INTO knowledge(school_id,topic,answer,source) VALUES(2,'Private topic','Other school only','Other')")
            other_staff=client.post("/api/staff-auth/accounts",headers=headers,json={
                "username":"otherstaff","display_name":"Other School Staff",
                "password":"secure-other-staff-123","school_id":2,"role":"staff"})
            assert other_staff.status_code==201,other_staff.text
            other_login=client.post("/api/staff-auth/login",json={
                "username":"otherstaff","password":"secure-other-staff-123"})
            assert other_login.status_code==200,other_login.text
            other_headers={"authorization":"Bearer "+other_login.json()["access_token"]}
            other_questions=client.get("/api/staff/mine/questions",headers=other_headers)
            assert other_questions.status_code==200,other_questions.text
            assert len(other_questions.json())==1
            other_question_id=other_questions.json()[0]["id"]
            assert other_questions.json()[0]["question"]=="Private other-school question"
            assert all(x["id"]!=other_question_id for x in client.get("/api/staff/mine/questions",headers=staff_headers).json())
            denied=client.patch(f"/api/staff/mine/questions/{other_question_id}",headers=staff_headers,json={
                "status":"assigned","assigned_to":"pgstaff"})
            assert denied.status_code==404,denied.text
            denied_reverse=client.patch(f"/api/staff/mine/questions/{question_id}",headers=other_headers,json={
                "status":"assigned","assigned_to":"otherstaff"})
            assert denied_reverse.status_code==404,denied_reverse.text
            other_parent=client.post("/api/auth/parents",headers=headers,json={
                "username":"otherparent","display_name":"Other School Parent",
                "password":"secure-other-parent-123","school_id":2})
            assert other_parent.status_code==201,other_parent.text
            other_parent_login=client.post("/api/auth/login",json={
                "username":"otherparent","password":"secure-other-parent-123"})
            assert other_parent_login.status_code==200,other_parent_login.text
            other_parent_headers={"authorization":"Bearer "+other_parent_login.json()["access_token"]}
            assert client.get("/api/auth/me",headers=other_parent_headers).json()["school_id"]==2
            blocked_chat=client.post("/api/chat",headers=other_parent_headers,json={"question":"What are school timings?"})
            assert blocked_chat.status_code==403,blocked_chat.text
            assert client.post("/api/staff-auth/logout",headers=staff_headers).status_code==200
            assert client.get("/api/staff-auth/me",headers=staff_headers).status_code==401
    finally:
        with psycopg.connect(admin,autocommit=True) as root:
            root.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
