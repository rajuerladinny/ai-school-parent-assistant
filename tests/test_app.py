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
