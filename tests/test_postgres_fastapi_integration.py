"""Actual FastAPI HTTP requests backed by a disposable PostgreSQL database.

The test temporarily patches the startup readiness gate, never changes the
production configuration gate. This isolates SQL/API compatibility from release approval.
"""
import os
import uuid
from urllib.parse import urlsplit,urlunsplit
import pytest


def test_postgres_index_sources_keep_policy_tenants(postgres_database, monkeypatch):
    from datetime import date
    from app import main

    monkeypatch.setenv("SCHOOL_DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("SCHOOL_POSTGRES_DSN", postgres_database)
    expected=set()
    with main.db() as connection:
        for school_id in (1,2,3):
            connection.execute("INSERT INTO schools(id,slug,name,active) VALUES(?,?,?,?)",
                (school_id,"school-" + str(school_id),"Fictional school",school_id != 3))
            row=connection.execute(
                "INSERT INTO policy_versions(school_id,policy_key,version,title,filename,content,status,effective_date) "
                "VALUES(?,'shared-fees',1,'Fees','fees.txt','Fictional school fee policy','approved',?) RETURNING id",
                (school_id,date.today())).fetchone()
            if school_id != 3:
                expected.add(("policy-" + str(row["id"]),school_id))
            connection.execute("INSERT INTO knowledge(school_id,topic,answer,source) VALUES(?,'Bus','Fictional bus route','Transport')",(school_id,))
            connection.execute("INSERT INTO documents(school_id,filename,title,content) VALUES(?,'library.txt','Library','Fictional library returns')",(school_id,))
    records=main.records_for_index()
    assert {(r["id"],r["school_id"]) for r in records if r["id"].startswith("policy-")} == expected
    assert all(r["school_id"] != 3 for r in records)
    for school_id in (1,2):
        assert {r["id"].split("-")[0] for r in records if r["school_id"] == school_id} == {"faq","doc","policy"}


@pytest.fixture(params=["owner", "restricted-login"])
def policy_upload_dsn(request, postgres_database, postgres_runtime_login):
    if request.param == "restricted-login":
        with postgres_runtime_login(postgres_database) as restricted:
            yield restricted
    else:
        yield postgres_database


@pytest.mark.parametrize("routes", [
    ("/api/policies", "/api/policies"),
    ("/api/school-admin/policies", "/api/school-admin/policies"),
    ("/api/policies", "/api/school-admin/policies"),
])
@pytest.mark.parametrize("existing_version", [0, 3])
def test_concurrent_postgres_policy_uploads_allocate_distinct_versions(postgres_database, policy_upload_dsn, monkeypatch, routes, existing_version):
    """Hold the school row so both requests overlap before their inserts commit."""
    import hashlib
    import time
    from concurrent.futures import ThreadPoolExecutor
    import psycopg
    from fastapi.testclient import TestClient
    from app import main, database_config

    monkeypatch.setenv("SCHOOL_ENV", "test")
    monkeypatch.setenv("SCHOOL_DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("SCHOOL_POSTGRES_DSN", policy_upload_dsn)
    monkeypatch.setenv("SCHOOL_ADMIN_KEY", "concurrent-policy-test-key")
    monkeypatch.setattr(database_config, "validate_configuration", lambda: "postgres")
    monkeypatch.setattr(main, "rebuild_index", lambda: False)
    with psycopg.connect(policy_upload_dsn) as runtime:
        runtime_user = runtime.execute("SELECT current_user").fetchone()[0]
    token = "concurrent-policy-test-token"
    with psycopg.connect(postgres_database) as connection:
        connection.execute("INSERT INTO schools(id,slug,name) VALUES(1,'demo','Demo School')")
        connection.execute("INSERT INTO schools(id,slug,name) VALUES(2,'other','Other School')")
        connection.execute(
            "INSERT INTO policy_versions(school_id,policy_key,version,title,filename,content,effective_date) "
            "VALUES(2,'concurrent-fees',20,'Other policy','other.txt','Other school policy','2026-01-01')")
        if existing_version:
            connection.execute(
                "INSERT INTO policy_versions(school_id,policy_key,version,title,filename,content,effective_date) "
                "VALUES(1,'concurrent-fees',%s,'Previous policy','old.txt','Previous policy content','2026-01-01')",
                (existing_version,))
        staff_id = connection.execute(
            "INSERT INTO staff_accounts(school_id,username,display_name,salt,password_hash,role) "
            "VALUES(1,'policyadmin','Policy Admin','salt','hash','school_admin') RETURNING id"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO staff_sessions(token_hash,staff_id,expires_at) VALUES(%s,%s,NOW()+INTERVAL '1 hour')",
            (hashlib.sha256(token.encode()).hexdigest(), staff_id))

    def upload(index):
        # Separate clients run requests on independent event loops/workers.
        with TestClient(main.app, raise_server_exceptions=False) as client:
            return client.post(routes[index], headers={
                "X-Admin-Key": "concurrent-policy-test-key", "Authorization": "Bearer " + token},
                data={"policy_key": "concurrent-fees", "title": "Upload " + str(index),
                      "effective_date": "2026-01-01"},
                files={"file": ("fees.txt", ("Fictional fee policy content from upload " + str(index)).encode())})

    with ThreadPoolExecutor(max_workers=2) as pool:
        with psycopg.connect(postgres_database) as blocker:
            blocker.execute("SELECT id FROM schools WHERE id=1 FOR UPDATE")
            futures = [pool.submit(upload, index) for index in range(2)]
            with psycopg.connect(postgres_database, autocommit=True) as monitor:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    waiting = monitor.execute(
                        "SELECT COUNT(*) FROM pg_stat_activity "
                        "WHERE datname=current_database() AND wait_event_type='Lock' AND usename=%s",
                        (runtime_user,)
                    ).fetchone()[0]
                    if waiting >= 2:
                        break
                    time.sleep(0.02)
                else:
                    pytest.fail("Both policy uploads must overlap while the school row is locked")
        # Releasing the row lock lets the uploads finish in transaction order.
        responses = [future.result(timeout=15) for future in futures]
    assert [response.status_code for response in responses] == [201, 201], [r.text for r in responses]
    assert sorted(response.json()["version"] for response in responses) == [existing_version + 1, existing_version + 2]
    assert len({response.json()["id"] for response in responses}) == 2
    with psycopg.connect(postgres_database) as connection:
        rows = connection.execute(
            "SELECT version,title,content,status FROM policy_versions "
            "WHERE school_id=1 AND policy_key='concurrent-fees' AND version>%s ORDER BY version",
            (existing_version,)).fetchall()
        assert [row[0] for row in rows] == [existing_version + 1, existing_version + 2]
        assert {row[1] for row in rows} == {"Upload 0", "Upload 1"}
        assert all(row[2].endswith(row[1][-1]) and row[3] == "draft" for row in rows)
        assert connection.execute(
            "SELECT version,content FROM policy_versions WHERE school_id=2"
        ).fetchall() == [(20, "Other school policy")]


def test_postgres_policy_allocation_rolls_back_and_releases_lock(postgres_database, monkeypatch):
    from app import policies
    from app.postgres_adapter import connect

    monkeypatch.setenv("SCHOOL_DATABASE_BACKEND", "postgres")
    with connect(postgres_database) as connection:
        connection.execute("INSERT INTO schools(id,slug,name) VALUES(1,'demo','Demo School')")
    with pytest.raises(RuntimeError, match="failed upload"):
        with connect(postgres_database) as connection:
            assert policies.next_version(connection, "rollback-policy") == 1
            connection.execute(
                "INSERT INTO policy_versions(school_id,policy_key,version,title,filename,content,effective_date) "
                "VALUES(1,'rollback-policy',1,'Failed upload','old.txt','Rolled back content','2026-01-01')")
            raise RuntimeError("failed upload")
    with connect(postgres_database) as connection:
        connection.execute("SET lock_timeout='2s'")
        assert policies.next_version(connection, "rollback-policy") == 1
        assert connection.execute("SELECT COUNT(*) FROM policy_versions").fetchone()[0] == 0


@pytest.fixture(params=["sqlite", "postgres"])
def parent_login_client(request, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main, auth, database_config

    backend = request.param
    monkeypatch.setenv("SCHOOL_ENV", "test")
    monkeypatch.setenv("SCHOOL_DATABASE_BACKEND", backend)
    monkeypatch.setattr(auth, "_login_attempts", {})
    monkeypatch.setattr(main, "rebuild_index", lambda: False)
    if backend == "postgres":
        target = request.getfixturevalue("postgres_database")
        monkeypatch.setenv("SCHOOL_POSTGRES_DSN", target)
        monkeypatch.setattr(database_config, "validate_configuration", lambda: "postgres")
    else:
        monkeypatch.setattr(main, "DB", str(tmp_path / "school-login.db"))
        main.setup()
    with main.db() as connection:
        connection.execute("INSERT INTO schools(id,slug,name) VALUES(1,'demo','Demo School') ON CONFLICT DO NOTHING")
        connection.execute("INSERT INTO schools(id,slug,name) VALUES(2,'second-school','Second School')")
        salt = "cd" * 16
        for school_id, username in ((1, "firstparent"), (2, "secondparent")):
            connection.execute(
                "INSERT INTO parent_accounts(school_id,username,display_name,salt,password_hash) "
                "VALUES(?,?,?,?,?)",
                (school_id, username, "Fictional Parent", salt, auth.digest("school-parent-password", salt)))
    with TestClient(main.app) as client:
        yield client, backend


def test_parent_login_requires_matching_school_code(parent_login_client):
    client, _ = parent_login_client
    for username, code, school_id in (("FIRSTPARENT", "demo", 1), ("SECONDPARENT", "second-school", 2)):
        login = client.post("/api/auth/login", json={
            "username": username, "password": "school-parent-password", "school_code": code})
        assert login.status_code == 200, login.text
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        assert client.get("/api/auth/me", headers=headers).json()["school_id"] == school_id
    for code, password in (("demo", "school-parent-password"),
                           ("missing-school", "school-parent-password"),
                           ("second-school", "incorrect-password")):
        denied = client.post("/api/auth/login", json={
            "username": "secondparent", "password": password, "school_code": code})
        assert denied.status_code == 401, denied.text
        assert denied.json() == {"detail": "Invalid credentials"}


def test_parent_login_legacy_unique_username_and_inactive_school(parent_login_client):
    client, _ = parent_login_client
    from app import main

    login = client.post("/api/auth/login", json={
        "username": "secondparent", "password": "school-parent-password"})
    assert login.status_code == 200, login.text
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    assert client.get("/api/auth/me", headers=headers).json()["school_id"] == 2
    with main.db() as connection:
        connection.execute("UPDATE schools SET active=FALSE WHERE id=2")
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    for extra in ({}, {"school_code": "second-school"}):
        denied = client.post("/api/auth/login", json={
            "username": "secondparent", "password": "school-parent-password", **extra})
        assert denied.status_code == 401, denied.text
        assert denied.json() == {"detail": "Invalid credentials"}


def test_parent_login_changing_school_code_does_not_reset_throttle(parent_login_client):
    client, _ = parent_login_client
    for index in range(5):
        denied = client.post("/api/auth/login", json={
            "username": "firstparent", "password": "incorrect-password",
            "school_code": "unknown-school-" + str(index)})
        assert denied.status_code == 401, denied.text
    blocked = client.post("/api/auth/login", json={
        "username": "FIRSTPARENT", "password": "school-parent-password", "school_code": "demo"})
    assert blocked.status_code == 429, blocked.text
    assert int(blocked.headers["Retry-After"]) > 0


@pytest.mark.parametrize("disabled", [None, "account", "school"])
def test_parent_login_duplicate_usernames_never_select_another_school(postgres_database, monkeypatch, disabled):
    from fastapi.testclient import TestClient
    from app import main, auth, database_config

    monkeypatch.setenv("SCHOOL_ENV", "test")
    monkeypatch.setenv("SCHOOL_DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("SCHOOL_POSTGRES_DSN", postgres_database)
    monkeypatch.setattr(database_config, "validate_configuration", lambda: "postgres")
    monkeypatch.setattr(main, "rebuild_index", lambda: False)
    salt = "ef" * 16
    with main.db() as connection:
        for school_id, code in ((1, "first-school"), (2, "second-school")):
            connection.execute("INSERT INTO schools(id,slug,name) VALUES(?,?,?)", (school_id, code, code))
            connection.execute(
                "INSERT INTO parent_accounts(school_id,username,display_name,salt,password_hash) VALUES(?,?,?,?,?)",
                (school_id, "sharedparent", code, salt, auth.digest("same-parent-password", salt)))
        if disabled == "account":
            connection.execute("UPDATE parent_accounts SET enabled=FALSE WHERE school_id=1")
        elif disabled == "school":
            connection.execute("UPDATE schools SET active=FALSE WHERE id=1")
    with TestClient(main.app) as client:
        payload = {"username": "sharedparent", "password": "same-parent-password"}
        unscoped = client.post("/api/auth/login", json=payload)
        assert unscoped.status_code == 401, unscoped.text
        assert unscoped.json() == {"detail": "Invalid credentials"}
        for school_id, code in ((1, "first-school"), (2, "second-school")):
            login = client.post("/api/auth/login", json={**payload, "school_code": code})
            if school_id == 1 and disabled:
                assert login.status_code == 401, login.text
                assert login.json() == {"detail": "Invalid credentials"}
                continue
            assert login.status_code == 200, login.text
            headers = {"Authorization": "Bearer " + login.json()["access_token"]}
            assert client.get("/api/auth/me", headers=headers).json()["school_id"] == school_id
        with main.db() as connection:
            rows = connection.execute(
                "SELECT a.school_id FROM parent_sessions s JOIN parent_accounts a ON a.id=s.parent_id ORDER BY a.school_id"
            ).fetchall()
            assert [row["school_id"] for row in rows] == ([2] if disabled else [1, 2])


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
@pytest.mark.parametrize("path,table", [
    ("/api/auth/parents", "parent_accounts"),
    ("/api/staff-auth/accounts", "staff_accounts"),
    ("/api/school-admin/parents", "parent_accounts"),
    ("/api/school-admin/staff", "staff_accounts"),
])
def test_account_creation_duplicate_username(backend, path, table, request, tmp_path, monkeypatch):
    """Duplicate account requests return 409 and leave the original account intact."""
    from fastapi.testclient import TestClient
    from app import main, auth, database_config

    monkeypatch.setenv("SCHOOL_ENV", "test")
    monkeypatch.setenv("SCHOOL_DATABASE_BACKEND", backend)
    monkeypatch.setenv("SCHOOL_ADMIN_KEY", "account-conflict-test-key")
    monkeypatch.setattr(main, "rebuild_index", lambda: False)
    if backend == "postgres":
        target = request.getfixturevalue("postgres_database")
        monkeypatch.setenv("SCHOOL_POSTGRES_DSN", target)
        # This test validates compatibility without opening the production gate.
        monkeypatch.setattr(database_config, "validate_configuration", lambda: "postgres")
        with main.db() as connection:
            connection.execute("INSERT INTO schools(id,slug,name) VALUES(1,'conflict-test','Test School')")
    else:
        monkeypatch.setattr(main, "DB", str(tmp_path / "accounts.db"))
        main.setup()

    salt = "ab" * 16
    with main.db() as connection:
        connection.execute(
            "INSERT INTO staff_accounts(school_id,username,display_name,salt,password_hash,role) "
            "VALUES(1,?,?,?,?,?)",
            ("conflictadmin", "Test Administrator", salt,
             auth.digest("administrator-test-password", salt), "school_admin"))

    with TestClient(main.app) as client:
        login = client.post("/api/staff-auth/login", json={
            "username": "conflictadmin", "password": "administrator-test-password"})
        assert login.status_code == 200, login.text
        headers = ({"Authorization": "Bearer " + login.json()["access_token"]}
                   if path.startswith("/api/school-admin/")
                   else {"X-Admin-Key": "account-conflict-test-key"})
        payload = {"username": "conflictuser", "display_name": "Original Account",
                   "password": "original-account-password"}
        if table == "staff_accounts":
            payload["role"] = "staff"
        created = client.post(path, headers=headers, json=payload)
        assert created.status_code == 201, created.text
        duplicate = client.post(path, headers=headers, json={
            **payload, "username": "CONFLICTUSER", "display_name": "Replacement Account",
            "password": "replacement-account-password"})
        assert duplicate.status_code == 409, duplicate.text
        assert duplicate.json()["detail"] == "Username already exists"
        with main.db() as connection:
            rows = connection.execute(
                f"SELECT id,display_name,salt,password_hash FROM {table} WHERE username=?",
                ("conflictuser",)).fetchall()
            assert len(rows) == 1
            assert rows[0]["id"] == created.json()["id"]
            assert rows[0]["display_name"] == "Original Account"
            assert rows[0]["password_hash"] == auth.digest(payload["password"], rows[0]["salt"])
        # A failed duplicate request must not poison subsequent transactions.
        following = client.post(path, headers=headers, json={**payload, "username": "followinguser"})
        assert following.status_code == 201, following.text


@pytest.mark.parametrize("database_identity", ["owner", "restricted-login"])
def test_fastapi_postgres_health_and_school_scoped_read(monkeypatch, postgres_runtime_login, database_identity):
    dsn=os.getenv("TEST_POSTGRES_URL")
    if not dsn:pytest.skip("Requires TEST_POSTGRES_URL")
    import psycopg
    from fastapi.testclient import TestClient
    from app import main,database_config
    from scripts.postgres_migrations import migrate
    from contextlib import ExitStack
    parts=urlsplit(dsn)
    name="school_api_"+uuid.uuid4().hex[:12]
    admin=urlunsplit((parts.scheme,parts.netloc,"/postgres",parts.query,parts.fragment))
    target=urlunsplit((parts.scheme,parts.netloc,"/"+name,parts.query,parts.fragment))
    with psycopg.connect(admin,autocommit=True) as root:
        root.execute(f'CREATE DATABASE "{name}"')
    runtime_connections = ExitStack()
    try:
        migrate(target)
        runtime_dsn = (runtime_connections.enter_context(postgres_runtime_login(target))
                       if database_identity == "restricted-login" else target)
        with psycopg.connect(target) as c:
            c.execute("INSERT INTO schools(id,slug,name) VALUES(1,'demo','Demo School')")
            c.execute("INSERT INTO knowledge(school_id,topic,answer,source) VALUES(1,'Timings','9 AM','Handbook')")
        monkeypatch.setenv("SCHOOL_DATABASE_BACKEND","postgres")
        monkeypatch.setenv("SCHOOL_POSTGRES_DSN",runtime_dsn)
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
            # School deactivation must revoke both token classes permanently.
            # Exercise this with real PostgreSQL transactions and API reads.
            with psycopg.connect(target) as revoke_conn:
                revoke_conn.execute("UPDATE schools SET active=FALSE WHERE id=1")
                revoke_conn.execute("UPDATE schools SET active=TRUE WHERE id=1")
            assert client.get("/api/auth/me",headers=parent_headers).status_code==401
            assert client.get("/api/staff-auth/me",headers=staff_headers).status_code==401
            # Re-login is required after reactivation.
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
            # School admins can administer only their own school's knowledge.
            for school_id,username in ((1,"adminone"),(2,"admintwo")):
                response=client.post("/api/staff-auth/accounts",headers=headers,json={
                    "username":username,"display_name":"School Administrator",
                    "password":"secure-admin-password-123","school_id":school_id,"role":"school_admin"})
                assert response.status_code==201,response.text
            def admin_headers(username):
                login=client.post("/api/staff-auth/login",json={
                    "username":username,"password":"secure-admin-password-123"})
                assert login.status_code==200,login.text
                return {"authorization":"Bearer "+login.json()["access_token"]}
            admin_one=admin_headers("adminone")
            admin_two=admin_headers("admintwo")
            assert client.get("/api/school-admin/knowledge").status_code==401
            assert client.get("/api/school-admin/knowledge",headers=staff_headers).status_code==403
            assert client.get("/api/school-admin/knowledge",headers=other_headers).status_code==403
            assert all(row["school_id"]==1 for row in client.get(
                "/api/school-admin/knowledge",headers=admin_one).json())
            assert all(row["school_id"]==2 for row in client.get(
                "/api/school-admin/knowledge",headers=admin_two).json())
            created_school_two=client.post("/api/school-admin/knowledge",headers=admin_two,json={
                "topic":"Private School Two","answer":"Only second school can see this",
                "source":"School Two"} )
            assert created_school_two.status_code==201,created_school_two.text
            second_id=created_school_two.json()["id"]
            assert all(row["id"]!=second_id for row in client.get(
                "/api/school-admin/knowledge",headers=admin_one).json())
            assert client.delete(f"/api/school-admin/knowledge/{second_id}",
                                 headers=admin_one).status_code==404
            assert client.delete(f"/api/school-admin/knowledge/{second_id}",
                                 headers=admin_two).status_code==200
            upload_two=client.post("/api/school-admin/documents",headers=admin_two,
                data={"title":"School Two Upload"},
                files={"file":("private.txt",b"School Two private document contains school-specific details.","text/plain")})
            assert upload_two.status_code==201,upload_two.text
            upload_two_id=upload_two.json()["id"]
            assert all(d["id"]!=upload_two_id for d in client.get(
                "/api/school-admin/documents",headers=admin_one).json())
            assert any(d["id"]==upload_two_id for d in client.get(
                "/api/school-admin/documents",headers=admin_two).json())
            assert client.post("/api/school-admin/documents",headers=staff_headers,
                files={"file":("denied.txt",b"Staff cannot upload this document to school.","text/plain")}).status_code==403
            assert client.delete(f"/api/school-admin/documents/{upload_two_id}",
                                 headers=admin_one).status_code==404
            assert client.delete(f"/api/school-admin/documents/{upload_two_id}",
                                 headers=admin_two).status_code==200
            with psycopg.connect(target) as seeded:
                seeded.execute(
                    "INSERT INTO policy_versions(school_id,policy_key,version,title,filename,content,"
                    "status,effective_date,created_at) VALUES "
                    "(2,'school2_rules',1,'School 2 Private Rules','rules.txt','Confidential school 2 policy',"
                    "'draft','2026-01-01',CURRENT_TIMESTAMP)")
            policies_one=client.get("/api/school-admin/policies",headers=admin_one)
            policies_two=client.get("/api/school-admin/policies",headers=admin_two)
            assert policies_one.status_code==200 and policies_two.status_code==200
            assert all(p["title"]!="School 2 Private Rules" for p in policies_one.json())
            assert any(p["title"]=="School 2 Private Rules" for p in policies_two.json())
            assert client.get("/api/school-admin/policies",headers=staff_headers).status_code==403
            assert client.get("/api/school-admin/policies").status_code==401
            policy_two=client.post("/api/school-admin/policies",headers=admin_two,
                data={"policy_key":"school2_policy","title":"School Two Policy",
                      "effective_date":"2026-01-01"},
                files={"file":("rules.txt",b"School Two exclusive policy for students and families.","text/plain")})
            assert policy_two.status_code==201,policy_two.text
            policy_two_id=policy_two.json()["id"]
            assert client.post(f"/api/school-admin/policies/{policy_two_id}/review",
                headers=admin_one,json={"approve":True}).status_code==404
            assert client.post(f"/api/school-admin/policies/{policy_two_id}/review",
                headers=staff_headers,json={"approve":True}).status_code==403
            approved_two=client.post(f"/api/school-admin/policies/{policy_two_id}/review",
                headers=admin_two,json={"approve":True})
            assert approved_two.status_code==200,approved_two.text
            assert approved_two.json()["status"]=="approved"
            assert client.post(f"/api/school-admin/policies/{policy_two_id}/review",
                headers=admin_two,json={"approve":True}).status_code==409
            assert all(p["id"]!=policy_two_id for p in client.get(
                "/api/school-admin/policies",headers=admin_one).json())
            # A School 2 policy conflict must not be resolvable by School 1.
            conflicting=client.post("/api/school-admin/knowledge",headers=admin_two,json={
                "topic":"school2_conflict","answer":"Outdated information must be retired",
                "source":"Old FAQ"})
            assert conflicting.status_code==201,conflicting.text
            conflicting_id=conflicting.json()["id"]
            draft=client.post("/api/school-admin/policies",headers=admin_two,
                data={"policy_key":"school2_conflict","title":"School Two Conflict",
                      "effective_date":"2026-01-01"},
                files={"file":("conflict.txt",b"School Two replacement policy overrides outdated FAQ.","text/plain")})
            assert draft.status_code==201,draft.text
            draft_id=draft.json()["id"]
            assert client.post(f"/api/school-admin/policies/{draft_id}/conflicts/scan",
                headers=admin_one).status_code==404
            scan=client.post(f"/api/school-admin/policies/{draft_id}/conflicts/scan",
                headers=admin_two)
            assert scan.status_code==200,scan.text
            assert scan.json()["pending"]==1
            assert client.post(f"/api/school-admin/policies/{draft_id}/review",
                headers=admin_two,json={"approve":True}).status_code==409
            assert client.post(f"/api/school-admin/legacy/faq/{conflicting_id}/deactivate",
                headers=admin_one).status_code==404
            assert client.post(f"/api/school-admin/legacy/faq/{conflicting_id}/deactivate",
                headers=staff_headers).status_code==403
            assert client.post(f"/api/school-admin/legacy/faq/{conflicting_id}/deactivate",
                headers=admin_two).status_code==200
            assert client.post(f"/api/school-admin/policies/{draft_id}/review",
                headers=admin_two,json={"approve":True}).status_code==200
            new_parent=client.post("/api/school-admin/parents",headers=admin_two,json={
                "username":"admincreatedparent","display_name":"Admin Created Parent",
                "password":"secure-created-parent-123"})
            assert new_parent.status_code==201,new_parent.text
            new_parent_id=new_parent.json()["id"]
            assert client.post("/api/school-admin/parents",headers=staff_headers,json={
                "username":"staffcannotcreate","display_name":"Staff Cannot Create",
                "password":"secure-created-parent-123"}).status_code==403
            assert client.post(f"/api/school-admin/parents/{new_parent_id}/disable",
                headers=admin_one).status_code==404
            new_login=client.post("/api/auth/login",json={
                "username":"admincreatedparent","password":"secure-created-parent-123"})
            assert new_login.status_code==200,new_login.text
            new_headers={"authorization":"Bearer "+new_login.json()["access_token"]}
            assert client.get("/api/auth/me",headers=new_headers).json()["school_id"]==2
            assert client.post(f"/api/school-admin/parents/{new_parent_id}/disable",
                headers=admin_two).status_code==200
            assert client.get("/api/auth/me",headers=new_headers).status_code==401
            new_staff=client.post("/api/school-admin/staff",headers=admin_two,json={
                "username":"admincreatedstaff","display_name":"Admin Created Staff",
                "password":"secure-created-staff-123","role":"staff"})
            assert new_staff.status_code==201,new_staff.text
            new_staff_id=new_staff.json()["id"]
            assert new_staff.json()["school_id"]==2
            assert client.post("/api/school-admin/staff",headers=admin_two,json={
                "username":"privilegeescalation","display_name":"Escalation Attempt",
                "password":"secure-created-staff-123","role":"school_admin"}).status_code==422
            assert client.post("/api/school-admin/staff",headers=staff_headers,json={
                "username":"staffcreatedstaff","display_name":"Staff Attempt",
                "password":"secure-created-staff-123","role":"staff"}).status_code==403
            assert client.post(f"/api/school-admin/staff/{new_staff_id}/disable",
                headers=admin_one).status_code==404
            staff_created_login=client.post("/api/staff-auth/login",json={
                "username":"admincreatedstaff","password":"secure-created-staff-123"})
            assert staff_created_login.status_code==200,staff_created_login.text
            staff_created_headers={"authorization":"Bearer "+staff_created_login.json()["access_token"]}
            assert client.get("/api/staff-auth/me",headers=staff_created_headers).json()["school_id"]==2
            assert client.post(f"/api/school-admin/staff/{new_staff_id}/disable",
                headers=admin_two).status_code==200
            assert client.get("/api/staff-auth/me",headers=staff_created_headers).status_code==401
            assert client.post(f"/api/school-admin/staff/{new_staff_id}/disable",
                headers=admin_two).status_code==404
            summary_one=client.get("/api/school-admin/notifications/summary",headers=admin_one)
            summary_two=client.get("/api/school-admin/notifications/summary",headers=admin_two)
            assert summary_one.status_code==200 and summary_two.status_code==200
            assert summary_one.json()["authenticated_parents"]==1
            assert summary_two.json()["authenticated_parents"]==0
            assert summary_one.json()["parent_read_receipts"]==0
            assert summary_two.json()["parent_read_receipts"]==0
            assert client.get("/api/school-admin/notifications/summary",
                              headers=staff_headers).status_code==403
            assert client.get("/api/school-admin/notifications/summary").status_code==401
            receipt_parent=client.post("/api/school-admin/parents",headers=admin_two,json={
                "username":"receiptparenttwo","display_name":"Receipt Parent Two",
                "password":"receipt-parent-password-123"})
            assert receipt_parent.status_code==201,receipt_parent.text
            receipt_parent_id=receipt_parent.json()["id"]
            with psycopg.connect(target) as seeded:
                parent_one_id=seeded.execute(
                    "SELECT id FROM parent_accounts WHERE school_id=1 AND enabled=TRUE LIMIT 1").fetchone()[0]
                seeded.execute(
                    "INSERT INTO parent_notification_reads(parent_id,policy_id) VALUES (%s,%s)",
                    (parent_one_id,policy_id))
                seeded.execute(
                    "INSERT INTO parent_notification_reads(parent_id,policy_id) VALUES (%s,%s)",
                    (receipt_parent_id,policy_two_id))
                # The database must reject cross-school receipts outright.
                with pytest.raises(psycopg.errors.CheckViolation):
                    with seeded.transaction():
                        seeded.execute(
                            "INSERT INTO parent_notification_reads(parent_id,policy_id) VALUES (%s,%s)",
                            (receipt_parent_id,policy_id))
            summary_one=client.get("/api/school-admin/notifications/summary",headers=admin_one)
            summary_two=client.get("/api/school-admin/notifications/summary",headers=admin_two)
            assert summary_one.status_code==200 and summary_two.status_code==200
            assert summary_one.json()["parent_read_receipts"]==1
            assert summary_two.json()["parent_read_receipts"]==1
            assert summary_one.json()["authenticated_parents"]==1
            assert summary_two.json()["authenticated_parents"]==1
            # Bootstrap refuses to overwrite an existing school administrator.
            from scripts.bootstrap_school_admin import bootstrap
            try:
                bootstrap(target,2,"anotheradmin","Another Admin","strong-bootstrap-password-123")
                assert False, "Bootstrap should reject a school with an existing admin"
            except ValueError as exc:
                assert "already has an administrator" in str(exc)
            # Chat answers and escalations must remain within the parent's school.
            from app import rag
            monkeypatch.setattr(rag,"enabled",lambda:False)
            original_rag_search=rag.search
            monkeypatch.setattr(rag,"search",lambda question,limit=4,school_id=1: [])
            with psycopg.connect(target) as seeded:
                seeded.execute("INSERT INTO knowledge(school_id,topic,answer,source,active) "
                               "VALUES(2,'SchoolTwoUniqueTerm','School two only answer','school-two',TRUE)")
            school_two_login=client.post("/api/auth/login",json={
                "username":"receiptparenttwo","password":"receipt-parent-password-123"})
            assert school_two_login.status_code==200,school_two_login.text
            school_two_headers={"authorization":"Bearer "+school_two_login.json()["access_token"]}
            answer_two=client.post("/api/chat",headers=school_two_headers,
                                   json={"question":"SchoolTwoUniqueTerm details"})
            assert answer_two.status_code==200,answer_two.text
            assert answer_two.json()["answer"]=="School two only answer"
            answer_one=client.post("/api/chat",headers=new_headers,
                                   json={"question":"SchoolTwoUniqueTerm details"})
            # Disabled parent sessions must not work.
            assert answer_one.status_code==401
            escalated=client.post("/api/chat",headers=school_two_headers,
                                  json={"question":"Unknown confidential question xyzzy"})
            assert escalated.status_code==200,escalated.text
            assert escalated.json()["needs_staff"] is True
            with psycopg.connect(target) as seeded:
                row=seeded.execute("SELECT school_id,parent_id FROM escalations WHERE id=%s",
                    (escalated.json()["escalation_id"],)).fetchone()
                assert row==(2,receipt_parent_id)
            monkeypatch.setattr(rag,"search",original_rag_search)
            # Document and escalation administration is tenant-scoped too.
            with psycopg.connect(target) as seeded:
                seeded.execute("INSERT INTO documents(school_id,filename,title,content,uploaded_at) "
                               "VALUES(2,'secret.txt','Private document','School 2 confidential information',CURRENT_TIMESTAMP)")
            own_docs=client.get("/api/school-admin/documents",headers=admin_one)
            other_docs=client.get("/api/school-admin/documents",headers=admin_two)
            assert own_docs.status_code==200 and other_docs.status_code==200
            assert all(d.get("school_id",1)==1 for d in own_docs.json())  # IDs checked below
            assert len(other_docs.json())==1
            other_doc_id=other_docs.json()[0]["id"]
            assert all(d["id"]!=other_doc_id for d in own_docs.json())
            assert client.delete(f"/api/school-admin/documents/{other_doc_id}",
                                 headers=admin_one).status_code==404
            assert client.delete(f"/api/school-admin/documents/{other_doc_id}",
                                 headers=admin_two).status_code==200
            assert client.get("/api/school-admin/documents",headers=staff_headers).status_code==403
            admin_one_escalations=client.get("/api/school-admin/escalations",headers=admin_one)
            admin_two_escalations=client.get("/api/school-admin/escalations",headers=admin_two)
            assert admin_one_escalations.status_code==200
            assert admin_two_escalations.status_code==200
            assert all(q["school_id"]==1 for q in admin_one_escalations.json())
            assert all(q["school_id"]==2 for q in admin_two_escalations.json())
            assert client.get("/api/school-admin/escalations",headers=staff_headers).status_code==403
            other_parent=client.post("/api/auth/parents",headers=headers,json={
                "username":"otherparent","display_name":"Other School Parent",
                "password":"secure-other-parent-123","school_id":2})
            assert other_parent.status_code==201,other_parent.text
            other_parent_login=client.post("/api/auth/login",json={
                "username":"otherparent","password":"secure-other-parent-123"})
            assert other_parent_login.status_code==200,other_parent_login.text
            other_parent_headers={"authorization":"Bearer "+other_parent_login.json()["access_token"]}
            assert client.get("/api/auth/me",headers=other_parent_headers).json()["school_id"]==2
            # Exercise SQL tenant isolation and escalation, not optional vector
            # retrieval; a developer's persistent Chroma index must not affect this.
            monkeypatch.setattr(rag,"search",lambda question,limit=4,school_id=1: [])
            blocked_chat=client.post("/api/chat",headers=other_parent_headers,json={"question":"What are school timings?"})
            assert blocked_chat.status_code==200,blocked_chat.text
            assert blocked_chat.json()["needs_staff"] is True
            with psycopg.connect(target) as seeded:
                assert seeded.execute("SELECT school_id FROM escalations WHERE id=%s",
                    (blocked_chat.json()["escalation_id"],)).fetchone()[0]==2
            own_questions=client.get("/api/parent/questions",headers=other_parent_headers)
            assert own_questions.status_code==200
            assert any(q["id"]==blocked_chat.json()["escalation_id"] for q in own_questions.json())
            assert all("question" in q and "status" in q for q in own_questions.json())
            other_inbox=client.get("/api/notifications/mine",headers=other_parent_headers)
            assert other_inbox.status_code==200,other_inbox.text
            assert all(p["policy_id"]!=policy_id for p in other_inbox.json())
            assert client.post(f"/api/notifications/mine/{policy_id}/read",
                               headers=other_parent_headers).status_code==404
            assert client.post(f"/api/notifications/mine/{policy_two_id}/read",
                               headers=other_parent_headers).status_code==200
            other_inbox=client.get("/api/notifications/mine",headers=other_parent_headers)
            assert any(p["policy_id"]==policy_two_id and p["is_read"] for p in other_inbox.json())
            # Direct database writes must obey tenant boundaries as well.
            with psycopg.connect(target) as seeded:
                with pytest.raises(psycopg.errors.CheckViolation):
                    with seeded.transaction():
                        seeded.execute("INSERT INTO parent_notification_reads(parent_id,policy_id) "
                                       "VALUES(%s,%s)",(receipt_parent_id,policy_id))

            parent_relogin=client.post("/api/auth/login",json={
                "username":"pgparent","password":"secure-parent-pass-123"})
            assert parent_relogin.status_code==200,parent_relogin.text
            parent_headers={"authorization":"Bearer "+parent_relogin.json()["access_token"]}
            assert client.get("/api/parent/questions",headers=parent_headers).status_code==200
            inbox=client.get("/api/notifications/mine",headers=parent_headers)
            assert inbox.status_code==200,inbox.text
            assert any(x["policy_id"]==policy_id for x in inbox.json())
            receipt=client.post(f"/api/notifications/mine/{policy_id}/read",headers=parent_headers)
            assert receipt.status_code==200,receipt.text
            assert any(x["policy_id"]==policy_id and x["is_read"] for x in client.get("/api/notifications/mine",headers=parent_headers).json())
            assert client.get("/api/notifications/admin/summary",headers=headers).status_code==200
            from app import staff as staff_routes
            monkeypatch.setenv("SCHOOL_ENV","production")
            try:
                assert client.get("/api/knowledge",headers=headers).status_code==403
                assert client.post("/api/knowledge",headers=headers,json={
                    "topic":"Blocked","answer":"Must never write to production","source":"test"}).status_code==403
                assert client.get("/api/documents",headers=headers).status_code==403
                assert client.get("/api/escalations",headers=headers).status_code==403
                assert client.get("/api/policies",headers=headers).status_code==403
                assert client.get("/api/notifications/admin/summary",headers=headers).status_code==403
                assert client.post("/api/auth/parents",headers=headers,json={
                    "username":"blockedparent","display_name":"Blocked Parent",
                    "password":"secure-blocked-123","school_id":1}).status_code==403
                assert client.post("/api/staff-auth/accounts",headers=headers,json={
                    "username":"blockedstaff","display_name":"Blocked Staff",
                    "password":"secure-blocked-123","school_id":1,"role":"staff"}).status_code==403
                assert client.get("/api/staff/questions",headers=headers).status_code==403
                assert client.patch(f"/api/staff/questions/{question_id}",headers=headers,json={
                    "status":"resolved","resolution":"legacy access denied"}).status_code==403
                assert client.get(f"/api/staff/questions/{question_id}/history",headers=headers).status_code==403
                assert client.get("/api/staff/mine/questions",headers=staff_headers).status_code==200
            finally:
                monkeypatch.setenv("SCHOOL_ENV","test")
            from app import rag
            class ScopedCollection:
                def __init__(self):self.scopes=[]
                def count(self):return 2
                def query(self,**kwargs):
                    self.scopes.append(kwargs["where"])
                    school=kwargs["where"]["school_id"]
                    return {"documents":[["School "+str(school)+" private content"]],
                            "metadatas":[[{"school_id":school,"source":"School "+str(school),"topic":"Private"}]],
                            "distances":[[0.1]]}
            class ScopedModel:
                def encode(self,*args,**kwargs):
                    class Vectors:
                        def tolist(self):return [[0.1,0.2]]
                    return Vectors()
            # Restore real retrieval before exercising the mocked vector backend.
            # Earlier tenant escalation assertions deliberately replace rag.search.
            monkeypatch.setattr(rag,"search",original_rag_search)
            collection=ScopedCollection()
            monkeypatch.setattr(rag,"_collection",collection)
            monkeypatch.setattr(rag,"_model",ScopedModel())
            assert rag.search("private",school_id=1)[0]["text"]=="School 1 private content"
            assert rag.search("private",school_id=2)[0]["text"]=="School 2 private content"
            assert collection.scopes==[{"school_id":1},{"school_id":2}]
            class LeakyCollection(ScopedCollection):
                def query(self,**kwargs):
                    self.scopes.append(kwargs["where"])
                    return {"documents":[["School 2 SECRET","School 1 public"]],
                            "metadatas":[[{"school_id":2,"source":"other","topic":"private"},
                                          {"school_id":1,"source":"own","topic":"public"}]],
                            "distances":[[0.01,0.2]]}
            monkeypatch.setattr(rag,"_collection",LeakyCollection())
            safe=rag.search("private",school_id=1)
            assert [x["text"] for x in safe]==["School 1 public"]
            assert all("SECRET" not in x["text"] for x in safe)
            # Exercise the HTTP chat boundary, not just the RAG helper: a
            # misbehaving vector backend must not leak cross-school passages.
            monkeypatch.setattr(rag,"enabled",lambda:True)
            chat_safe=client.post("/api/chat",headers=parent_headers,
                                  json={"question":"private school details"})
            assert chat_safe.status_code==200,chat_safe.text
            assert chat_safe.json()["needs_staff"] is False
            assert "SECRET" not in chat_safe.json()["answer"]
            assert chat_safe.json()["source"]=="own"
            chat_other=client.post("/api/chat",headers=other_parent_headers,
                                   json={"question":"private school details"})
            assert chat_other.status_code==200,chat_other.text
            assert chat_other.json()["needs_staff"] is False
            assert chat_other.json()["answer"]=="School 2 SECRET"
            assert chat_other.json()["source"]=="other"
            assert "School 1 public" not in chat_other.json()["answer"]
            for invalid_school in (0,-1,None,True,"2"):
                with pytest.raises(ValueError):
                    rag.search("school policies",school_id=invalid_school)
            assert all(x["school_id"]==1 for x in client.get("/api/knowledge",headers=headers).json())
            assert all(x["school_id"]==1 for x in client.get("/api/escalations",headers=headers).json())
            assert client.get("/api/parent/questions").status_code==401
            assert client.get("/api/notifications/mine").status_code==401
            assert client.post("/api/staff-auth/logout",headers=staff_headers).status_code==200
            assert client.get("/api/staff-auth/me",headers=staff_headers).status_code==401
    finally:
        runtime_connections.close()
        with psycopg.connect(admin,autocommit=True) as root:
            root.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
