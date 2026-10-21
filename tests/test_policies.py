from datetime import date, timedelta
from fastapi.testclient import TestClient
from app import main, policies
import pytest

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB", str(tmp_path / "policies.db"))
    monkeypatch.setenv("SCHOOL_ADMIN_KEY", "test-key")
    monkeypatch.setattr(main, "rebuild_index", lambda: True)
    policies.configure(main.db, main.auth, main.extract_text, main.rebuild_index)
    main.setup()
    return TestClient(main.app)

def upload(client, content, effective, key="fee-policy"):
    return client.post("/api/policies", headers={"X-Admin-Key":"test-key"},
        data={"policy_key":key,"title":"Fee policy","effective_date":effective},
        files={"file":("fees.txt",content.encode("utf-8"))})

def test_approval_and_versioned_effective_date(client):
    today = date.today()
    old = upload(client,"School fees are payable by 10 June. Contact accounts office.",
                 (today-timedelta(days=1)).isoformat())
    assert old.status_code == 201 and old.json()["status"] == "draft"
    assert client.get("/api/policies/active").json() == []
    old_id=old.json()["id"]
    assert client.post(f"/api/policies/{old_id}/review",json={"approve":True},
                       headers={"X-Admin-Key":"test-key"}).status_code == 200
    assert client.get("/api/policies/active").json()[0]["version"] == 1
    future = upload(client,"School fees are payable by 20 June. Contact accounts office.",
                    (today+timedelta(days=10)).isoformat())
    assert future.json()["version"] == 2
    new_id=future.json()["id"]
    assert client.post(f"/api/policies/{new_id}/review",json={"approve":True},
                       headers={"X-Admin-Key":"test-key"}).status_code == 200
    assert client.get("/api/policies/active").json()[0]["version"] == 1
    with main.db() as c:
        assert policies.current_versions(c, (today+timedelta(days=11)).isoformat())[0]["version"] == 2
        assert "10 June" in policies.active_records(c, today.isoformat())[0]["text"]
        assert "20 June" in policies.active_records(c, (today+timedelta(days=11)).isoformat())[0]["text"]

def test_reject_keeps_old_version_and_requires_auth(client):
    today=date.today().isoformat()
    assert upload(client,"School fees payable at the office on weekdays.",today).status_code == 201
    assert client.get("/api/policies").status_code == 401
    item=client.get("/api/policies",headers={"X-Admin-Key":"test-key"}).json()[0]
    endpoint=f"/api/policies/{item['id']}/review"
    assert client.post(endpoint,json={"approve":False},headers={"X-Admin-Key":"test-key"}).json()["status"] == "rejected"
    assert client.post(endpoint,json={"approve":True},headers={"X-Admin-Key":"test-key"}).status_code == 409
    assert client.get("/api/policies/active").json() == []

def test_invalid_policy_key_and_date(client):
    assert upload(client,"School fees payable at the office on weekdays.",date.today().isoformat(),key="../oops").status_code == 422
    assert upload(client,"School fees payable at the office on weekdays.","next week").status_code == 422


@pytest.mark.parametrize("routes", [
    ("/api/policies", "/api/policies"),
    ("/api/school-admin/policies", "/api/school-admin/policies"),
    ("/api/policies", "/api/school-admin/policies"),
])
def test_concurrent_sqlite_policy_uploads(client, monkeypatch, routes):
    import hashlib
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from app import school_admin

    monkeypatch.setenv("SCHOOL_DATABASE_BACKEND", "sqlite")
    token = "sqlite-policy-concurrency-token"
    with main.db() as connection:
        row = connection.execute(
            "INSERT INTO staff_accounts(school_id,username,display_name,salt,password_hash,role) "
            "VALUES(1,'policyadmin','Policy Admin','salt','hash','school_admin') RETURNING id"
        ).fetchone()
        connection.execute("INSERT INTO staff_sessions(token_hash,staff_id,expires_at) VALUES(?,?,?)",
                           (hashlib.sha256(token.encode()).hexdigest(), row["id"], "2099-01-01T00:00:00+00:00"))
    monkeypatch.setattr(school_admin, "_reindex", main.rebuild_index)
    start = threading.Barrier(2)

    def concurrent_upload(index):
        # A client per worker gives each request its own event loop.
        worker = TestClient(main.app, raise_server_exceptions=False)
        try:
            start.wait(timeout=5)
            return worker.post(routes[index], headers={
                "X-Admin-Key": "test-key", "Authorization": "Bearer " + token},
                data={"policy_key": "parallel-fees", "title": "Upload " + str(index),
                      "effective_date": date.today().isoformat()},
                files={"file": ("fees.txt", b"Fictional school policy content for simultaneous uploads.")})
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(concurrent_upload, range(2)))
    assert [response.status_code for response in responses] == [201, 201], [r.text for r in responses]
    assert sorted(response.json()["version"] for response in responses) == [1, 2]
    with main.db() as connection:
        rows = connection.execute(
            "SELECT version,title,status FROM policy_versions WHERE policy_key='parallel-fees' ORDER BY version"
        ).fetchall()
        assert [row["version"] for row in rows] == [1, 2]
        assert {row["title"] for row in rows} == {"Upload 0", "Upload 1"}
        assert all(row["status"] == "draft" for row in rows)
