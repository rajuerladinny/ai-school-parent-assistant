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
