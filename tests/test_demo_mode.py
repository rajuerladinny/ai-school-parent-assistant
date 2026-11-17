"""Public demo mode: seeded fictional data, read-only staff portal, no stored visitor input."""
import pytest
from fastapi.testclient import TestClient

from app import main, staff, policies, conflicts, notifications, auth, parent_questions, demo

ADMIN = {"X-Admin-Key": "demo-test-key"}


def _configure(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB", str(tmp_path / "demo.db"))
    monkeypatch.setenv("SCHOOL_ADMIN_KEY", "demo-test-key")
    monkeypatch.setattr(main, "rebuild_index", lambda: True)
    monkeypatch.setattr(main.rag, "search", lambda *args, **kwargs: [])
    monkeypatch.setattr(main.rag, "enabled", lambda: True)
    policies.configure(main.db, main.auth, main.extract_text, main.rebuild_index)
    conflicts.configure(main.db, main.auth, main.rebuild_index)
    notifications.configure(main.db, main.auth)
    auth.configure(main.db, main.auth)
    staff.configure(main.db, main.auth)
    parent_questions.configure(main.db)


@pytest.fixture
def demo_client(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("SCHOOL_DEMO_MODE", "1")
    main.setup()
    return TestClient(main.app)


@pytest.fixture
def normal_client(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.delenv("SCHOOL_DEMO_MODE", raising=False)
    main.setup()
    return TestClient(main.app)


def demo_parent(client):
    r = client.post("/api/auth/login", json={"school_code": demo.SCHOOL_CODE,
                                             "username": demo.PARENT_USERNAME,
                                             "password": demo.PARENT_PASSWORD})
    assert r.status_code == 200
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def test_demo_info_publishes_demo_values(demo_client):
    info = demo_client.get("/api/demo").json()
    assert info["enabled"] is True
    assert info["admin_key"] == "demo-test-key"
    assert info["parent_username"] == demo.PARENT_USERNAME
    assert info["sample_questions"]
    assert demo_client.get("/api/health").json()["demo_mode"] is True


def test_demo_info_hidden_outside_demo_mode(normal_client):
    assert normal_client.get("/api/demo").json() == {"enabled": False}


def test_demo_seeds_fictional_content_once(demo_client):
    docs = demo_client.get("/api/documents", headers=ADMIN).json()
    assert [d["title"] for d in docs] == ["Parent handbook 2026"]
    statuses = sorted(p["status"] for p in demo_client.get("/api/policies", headers=ADMIN).json())
    assert statuses == ["approved", "draft"]
    questions = demo_client.get("/api/staff/questions", headers=ADMIN).json()
    assert sorted(q["status"] for q in questions) == ["assigned", "open", "resolved"]
    fees = [k for k in demo_client.get("/api/knowledge", headers=ADMIN).json() if k["topic"] == "Fees"]
    assert fees and not fees[0]["active"]

    main.setup()  # a restart against the same database must not duplicate anything
    assert len(demo_client.get("/api/documents", headers=ADMIN).json()) == 1
    assert len(demo_client.get("/api/staff/questions", headers=ADMIN).json()) == 3


def test_demo_parent_sees_seeded_updates_and_replies(demo_client):
    h = demo_parent(demo_client)
    updates = demo_client.get("/api/notifications/mine", headers=h).json()
    assert [u["title"] for u in updates] == ["Fee policy 2026"]
    assert demo_client.post(f"/api/notifications/mine/{updates[0]['policy_id']}/read", headers=h).status_code == 200
    mine = demo_client.get("/api/parent/questions", headers=h).json()
    assert any(q["status"] == "resolved" and q["resolution"] for q in mine)


@pytest.mark.parametrize("method,path,kwargs", [
    ("post", "/api/knowledge", {"json": {"topic": "Spam", "answer": "Visitor text", "source": "Anyone"}}),
    ("delete", "/api/knowledge/1", {}),
    ("post", "/api/auth/parents", {"json": {"username": "visitor", "display_name": "Visitor",
                                            "password": "visitor-password-123"}}),
    ("patch", "/api/staff/questions/1", {"json": {"status": "resolved", "resolution": "Visitor reply"}}),
    ("post", "/api/policies/1/review", {"json": {"approve": False}}),
    ("post", "/api/conflicts/legacy/faq/1/activate", {}),
    ("post", "/api/staff-auth/accounts", {"json": {"username": "visitor", "display_name": "Visitor",
                                                   "password": "visitor-password-123", "role": "staff"}}),
])
def test_demo_blocks_staff_changes(demo_client, method, path, kwargs):
    r = getattr(demo_client, method)(path, headers=ADMIN, **kwargs)
    assert r.status_code == 403
    assert "read-only" in r.json()["detail"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_demo_document_upload_blocked(demo_client):
    r = demo_client.post("/api/documents", headers=ADMIN, data={"title": "Visitor"},
                         files={"file": ("visitor.txt", b"Visitor supplied content " * 5, "text/plain")})
    assert r.status_code == 403


def test_demo_does_not_store_visitor_questions(demo_client):
    before = len(demo_client.get("/api/staff/questions", headers=ADMIN).json())
    for headers in ({}, demo_parent(demo_client)):
        r = demo_client.post("/api/chat", headers=headers, json={"question": "Visitor question about the moon?"})
        body = r.json()
        assert r.status_code == 200 and body["needs_staff"] is True
        assert body["demo"] is True and body["escalation_id"] is None
    assert len(demo_client.get("/api/staff/questions", headers=ADMIN).json()) == before


def test_normal_mode_still_allows_staff_changes(normal_client):
    r = normal_client.post("/api/knowledge", headers=ADMIN,
                           json={"topic": "Uniform", "answer": "Navy sweater daily.", "source": "Handbook"})
    assert r.status_code == 201
    assert normal_client.post("/api/chat", json={"question": "Unknown question here?"}).json()["escalation_id"]


def test_demo_mode_refused_in_production(monkeypatch):
    monkeypatch.setenv("SCHOOL_DEMO_MODE", "1")
    monkeypatch.setenv("SCHOOL_ENV", "production")
    with pytest.raises(RuntimeError, match="production"):
        demo.validate()


def test_demo_mode_requires_admin_key(monkeypatch):
    monkeypatch.setenv("SCHOOL_DEMO_MODE", "1")
    monkeypatch.delenv("SCHOOL_ENV", raising=False)
    monkeypatch.delenv("SCHOOL_ADMIN_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SCHOOL_ADMIN_KEY"):
        demo.validate()


def test_best_sentences_quotes_relevant_lines_without_headings(monkeypatch):
    from app import rag
    monkeypatch.setattr(rag, "_load", lambda: False)  # keyword fallback; no model download in tests
    passage = ("# Handbook\n\n## Lunch\n\nThe canteen serves a hot lunch every day. "
               "Sunrise Valley is a nut-free school, so please do not send food containing nuts.\n\n"
               "## Library\n\nThe library is open from 8:00 AM to 4:00 PM on school days.")
    answer = rag.best_sentences("Is the school nut-free?", [passage], limit=1)
    assert answer == "Sunrise Valley is a nut-free school, so please do not send food containing nuts."
    assert "#" not in rag.best_sentences("library hours", [passage])
    assert rag.best_sentences("anything", ["# Only a heading"]) == ""


def test_onnx_embedder_used_when_requested(monkeypatch):
    from app import rag
    monkeypatch.setenv("RAG_EMBEDDER", "onnx")
    created = []
    monkeypatch.setattr(rag, "_OnnxEmbedder", lambda: created.append(1) or "onnx-embedder")
    assert rag._embedder() == "onnx-embedder" and created == [1]
