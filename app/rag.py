"""Optional local RAG retrieval with ChromaDB + Sentence Transformers.

Install requirements-rag.txt to enable dense vector search. The app remains usable
without the optional dependencies and falls back to the existing FAQ matching.
"""
import os
import hashlib
from typing import Iterable

_model = None
_client = None
_collection = None
_last_fingerprint = None

def chunk_text(text: str, chunk_size: int = 900, overlap: int = 120) -> list[str]:
    text = " ".join(text.split())
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks

def _load():
    global _model, _client, _collection
    if _collection is not None:
        return True
    try:
        import chromadb
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(os.getenv("RAG_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"))
        _client = chromadb.PersistentClient(path=os.getenv("RAG_VECTOR_PATH", "./chroma_data"))
        _collection = _client.get_or_create_collection(
            name="school_knowledge",
            metadata={"hnsw:space": "cosine"},
        )
        return True
    except Exception:
        return False

def enabled() -> bool:
    return _load()

def rebuild(records: Iterable[dict]) -> bool:
    global _last_fingerprint
    if not _load():
        return False
    docs = []
    ids = []
    metadatas = []
    for record in records:
        for i, chunk in enumerate(chunk_text(str(record.get("text", "")))):
            docs.append(chunk)
            ids.append(hashlib.sha256(f"{record.get('id')}:{i}:{chunk}".encode()).hexdigest()[:32])
            metadatas.append({"school_id":int(record.get("school_id",1)),
                              "source": str(record.get("source", "School information"))[:200],
                              "topic": str(record.get("topic", "Document"))[:200]})
    fingerprint = hashlib.sha256("\n".join(ids).encode()).hexdigest()
    if fingerprint == _last_fingerprint:
        return True
    try:
        existing = _collection.get(include=[])
        if existing.get("ids"):
            _collection.delete(ids=existing["ids"])
        if docs:
            vectors = _model.encode(docs, normalize_embeddings=True).tolist()
            _collection.add(ids=ids, documents=docs, metadatas=metadatas, embeddings=vectors)
        _last_fingerprint = fingerprint
        return True
    except Exception:
        return False

def search(question: str, limit: int = 4, school_id: int = 1) -> list[dict]:
    if not isinstance(school_id, int) or isinstance(school_id, bool) or school_id < 1:
        raise ValueError("A valid school_id is required for retrieval")
    if not _load() or _collection.count() == 0:
        return []
    try:
        vector = _model.encode([question], normalize_embeddings=True).tolist()[0]
        result = _collection.query(query_embeddings=[vector], where={"school_id":school_id}, n_results=min(limit, _collection.count()))
        output = []
        for i, text in enumerate((result.get("documents") or [[]])[0]):
            metadata = (result.get("metadatas") or [[]])[0][i] or {}
            distance = (result.get("distances") or [[]])[0][i]
            output.append({"text": text, "source": metadata.get("source", "School information"),
                           "topic": metadata.get("topic", "Document"), "distance": distance})
        return output
    except Exception:
        return []
