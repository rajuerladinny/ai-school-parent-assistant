import pytest
from fastapi.testclient import TestClient
from app import main

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(main,"DB",str(tmp_path/"test.db"))
    monkeypatch.setenv("SCHOOL_ADMIN_KEY","test-key")
    main.setup()
    return TestClient(main.app)

def test_answer(client):
    r=client.post("/api/chat",json={"question":"What are school timings?"})
    assert r.status_code==200 and "8:30" in r.json()["answer"]

def test_unknown(client):
    r=client.post("/api/chat",json={"question":"Where is the swimming pool?"})
    assert r.json()["needs_staff"] is True
    assert len(client.get("/api/escalations",headers={"X-Admin-Key":"test-key"}).json())==1

def test_auth(client):
    x={"topic":"Lunch","answer":"Lunch is at noon.","source":"Handbook"}
    assert client.post("/api/knowledge",json=x).status_code==401
    assert client.post("/api/knowledge",json=x,headers={"X-Admin-Key":"test-key"}).status_code==201

def test_health_reports_vector_mode(client):
    r=client.get("/api/health")
    assert r.status_code==200
    assert "vector_search_enabled" in r.json()

def test_document_upload_requires_admin(client):
    r=client.post("/api/documents",files={"file":("policy.txt",b"This is an approved school policy document with enough text for the test.")})
    assert r.status_code==401

def test_upload_text_document_and_list(client):
    h={"X-Admin-Key":"test-key"}
    text=("Approved school policy: library hours are Monday to Friday from 9 AM to 2 PM. "
          "Students must return library books by the announced due date. "*3)
    r=client.post("/api/documents",headers=h,data={"title":"Library Policy"},
                  files={"file":("library-policy.txt",text.encode())})
    assert r.status_code==201
    assert r.json()["filename"]=="library-policy.txt"
    docs=client.get("/api/documents",headers=h).json()
    assert any(d["title"]=="Library Policy" for d in docs)

def test_upload_rejects_unsupported_type(client):
    h={"X-Admin-Key":"test-key"}
    r=client.post("/api/documents",headers=h,data={"title":"Bad"},
                  files={"file":("image.exe",b"some content")})
    assert r.status_code==415

def test_delete_document(client):
    h={"X-Admin-Key":"test-key"}
    text=b"Approved policy information. School library hours are Monday through Friday. Contact the office for more information."
    r=client.post("/api/documents",headers=h,data={"title":"Delete me"},
                  files={"file":("delete.txt",text)})
    assert r.status_code==201
    doc_id=r.json()["id"]
    assert client.delete(f"/api/documents/{doc_id}",headers=h).json()["deleted"] is True

def test_weak_vector_match_escalates_instead_of_keyword_guess(client, monkeypatch):
    # Vector index is available but no result is confident enough.
    monkeypatch.setattr(main.rag, "enabled", lambda: True)
    monkeypatch.setattr(main.rag, "search", lambda question, limit=4: [])
    r = client.post("/api/chat", json={"question":"What are the school timings?"})
    assert r.status_code == 200
    assert r.json()["needs_staff"] is True
    assert r.json()["retrieval"] == "no-confident-match"

def test_vector_result_includes_source(client, monkeypatch):
    monkeypatch.setattr(main.rag, "search", lambda question, limit=4: [
        {"text":"Library closes at 2 PM.","source":"Approved library policy",
         "topic":"Library","distance":0.12}])
    monkeypatch.setattr(main, "generate_grounded_answer",
                        lambda question, passages: ("Library closes at 2 PM.", "extractive-rag"))
    r = client.post("/api/chat", json={"question":"When does the library close?"})
    assert r.status_code == 200
    assert r.json()["needs_staff"] is False
    assert r.json()["retrieval"] == "chroma-vector"
    assert r.json()["sources"][0]["source"] == "Approved library policy"
