"""Local vector integration checks; run with pip install -r requirements-rag.txt.

These tests use a temporary Chroma collection and a deterministic local embedding
function, so they do not download a model or contact a paid service. They verify
indexing, retrieval, source metadata, and deletion. For a real-model smoke test,
run scripts/smoke_rag.py after downloading the embedding model.
"""
import pytest
from app import rag

class LocalEmbedding:
    """Tiny deterministic offline embedding for testing Chroma persistence."""
    def __call__(self, input):
        import numpy as np
        words = ("library", "book", "admission", "fee", "holiday", "bus")
        return [np.asarray([float(word in text.lower()) for word in words] + [0.01], dtype="float32") for text in input]

@pytest.fixture
def local_rag(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHOOL_ENV", "test")
    chromadb = pytest.importorskip("chromadb")
    monkeypatch.setattr(rag, "_model", None)
    monkeypatch.setattr(rag, "_client", chromadb.PersistentClient(path=str(tmp_path / "vectors")))
    monkeypatch.setattr(rag, "_collection", rag._client.get_or_create_collection(
        name="school_knowledge", metadata={"hnsw:space": "cosine"}))
    monkeypatch.setattr(rag, "_last_fingerprint", None)
    class Encoder:
        def encode(self, texts, normalize_embeddings=True):
            import numpy as np
            return np.stack(LocalEmbedding()(texts))
    monkeypatch.setattr(rag, "_model", Encoder())
    return rag

def test_vector_index_and_source(local_rag):
    assert local_rag.rebuild([
        {"id": "doc-1", "topic": "Library", "source": "Library policy",
         "text": "The library book return desk is open on weekdays."},
        {"id": "doc-2", "topic": "Admissions", "source": "Admission guide",
         "text": "The admission fee details are available from the office."}
    ])
    result = local_rag.search("When can I return a library book?")
    assert result and result[0]["source"] == "Library policy"
    assert result[0]["distance"] <= 0.62

def test_reindex_removes_deleted_document(local_rag):
    assert local_rag.rebuild([{"id": "doc-1", "topic": "Library",
        "source": "Old policy", "text": "Library book returns."}])
    assert local_rag.rebuild([{"id": "doc-2", "topic": "Admissions",
        "source": "New policy", "text": "Admission fee information."}])
    results = local_rag.search("admission fee")
    assert results and all(item["source"] != "Old policy" for item in results)

def test_chunk_overlap():
    parts = rag.chunk_text(" ".join(["library"] * 300), chunk_size=100, overlap=20)
    assert len(parts) > 1
    assert all(len(part) <= 100 for part in parts)


def test_policy_index_uses_real_collection_with_school_filters(local_rag, policy_index_database):
    main=policy_index_database
    assert main.rebuild_index()
    for school_id, marker in ((1,"ONE"),(2,"TWO")):
        found=local_rag.search("fee policy",school_id=school_id)
        assert any("School " + marker + " fee policy" in row["text"] for row in found)
        assert all("School " + ("TWO" if school_id == 1 else "ONE") not in row["text"] for row in found)
        assert all(word not in row["text"] for row in found for word in ("FUTURE","DRAFT","REJECTED","THREE"))
    assert local_rag.search("fee policy",school_id=3) == []


def test_parent_chat_retrieves_only_own_school_policy(local_rag, policy_index_database):
    from fastapi.testclient import TestClient
    from app import auth
    main=policy_index_database
    salt="ab" * 16
    with main.db() as connection:
        for school_id in (1,2):
            connection.execute("INSERT INTO parent_accounts(school_id,username,display_name,salt,password_hash) VALUES(?,?,?,?,?)",
                (school_id,"parent" + str(school_id),"Fictional Parent",salt,auth.digest("parent-policy-test-password",salt)))
    with TestClient(main.app) as client:
        for school_id, code, marker, filename in ((1,"demo","ONE","one.txt"),(2,"two","TWO","two.txt")):
            login=client.post("/api/auth/login",json={"school_code":code,"username":"parent" + str(school_id),
                                                      "password":"parent-policy-test-password"})
            assert login.status_code == 200,login.text
            response=client.post("/api/chat",headers={"Authorization":"Bearer " + login.json()["access_token"]},
                                 json={"question":"What is the fee policy?"})
            assert response.status_code == 200,response.text
            data=response.json()
            assert data["needs_staff"] is False
            assert data["retrieval"] == "chroma-vector"
            assert "School " + marker in data["answer"]
            assert filename in data["source"]
            assert all(word not in data["answer"] for word in ("FUTURE","DRAFT","REJECTED","THREE"))
            assert "School " + ("TWO" if school_id == 1 else "ONE") not in data["answer"]


def test_reindex_removes_rejected_policies_and_disabled_schools(local_rag, policy_index_database):
    main=policy_index_database
    assert main.rebuild_index()
    with main.db() as connection:
        connection.execute("UPDATE policy_versions SET status='rejected' WHERE id=201")
    assert main.rebuild_index()
    assert all("School TWO fee policy" not in row["text"] for row in local_rag.search("fee policy",school_id=2))
    with main.db() as connection:
        connection.execute("UPDATE schools SET active=FALSE WHERE id=2")
    assert main.rebuild_index()
    assert local_rag.search("bus library fee policy",school_id=2) == []
    assert local_rag.search("fee policy",school_id=1)


def test_same_source_id_and_text_can_exist_in_different_schools(local_rag):
    records=[{"id":"policy-shared","school_id":school_id,"source":"School policy","text":"Fictional fee policy"}
             for school_id in (1,2)]
    assert local_rag.rebuild(records)
    assert local_rag._collection.count() == 2
    assert local_rag.search("fee policy",school_id=1)
    assert local_rag.search("fee policy",school_id=2)


@pytest.mark.parametrize("change", [{"source":"New source","topic":"New topic"},{"school_id":2}])
def test_reindex_refreshes_changed_metadata(local_rag, change):
    original={"id":"policy-1","school_id":1,"source":"Old source","topic":"Old topic","text":"Fictional fee policy"}
    assert local_rag.rebuild([original])
    changed={**original,**change}
    assert local_rag.rebuild([changed])
    result=local_rag.search("fee policy",school_id=changed["school_id"])
    assert len(result) == 1
    assert result[0]["source"] == changed["source"]
    assert result[0]["topic"] == changed["topic"]
    if changed["school_id"] == 2:
        assert local_rag.search("fee policy",school_id=1) == []


@pytest.mark.parametrize("school_id", [0,-1,None,True,"2"])
def test_reindex_rejects_invalid_school_before_mutating_collection(local_rag, school_id):
    record={"id":"policy-1","school_id":1,"source":"Policy","text":"Fictional fee policy"}
    assert local_rag.rebuild([record])
    with pytest.raises(ValueError,match="school_id"):
        local_rag.rebuild([{**record,"school_id":school_id}])
    assert local_rag.search("fee policy",school_id=1)
