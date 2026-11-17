"""Optional local RAG retrieval with ChromaDB + Sentence Transformers.

Install requirements-rag.txt to enable dense vector search. The app remains usable
without the optional dependencies and falls back to the existing FAQ matching.
"""
import os
import re
import hashlib
import json
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

class _OnnxEmbedder:
    """all-MiniLM-L6-v2 via ChromaDB's bundled ONNX runtime: same model, no PyTorch.

    Uses far less memory than Sentence Transformers, so semantic search fits small
    free hosting tiers. Exposes the same encode() interface the rest of this module uses.
    """
    def __init__(self):
        from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
        self._fn = ONNXMiniLM_L6_V2()

    def encode(self, texts, normalize_embeddings=True):
        import numpy as np
        texts = list(texts)
        # Small batches keep ONNX Runtime's working memory low on small instances.
        vectors = np.array([v for i in range(0, len(texts), 8) for v in self._fn(texts[i:i + 8])],
                           dtype="float32").reshape(len(texts), -1)
        if normalize_embeddings:
            vectors = vectors / np.clip(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12, None)
        return vectors


def _embedder():
    """Sentence Transformers when installed; otherwise (or with RAG_EMBEDDER=onnx) the ONNX build."""
    if os.getenv("RAG_EMBEDDER", "").lower() != "onnx":
        try:
            from sentence_transformers import SentenceTransformer
            return SentenceTransformer(os.getenv("RAG_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"))
        except ImportError:
            pass
    return _OnnxEmbedder()


def _load():
    global _model, _client, _collection
    # The optional ChromaDB dependency has unresolved security advisories.
    # Do not initialize or use vector retrieval in production, even if it was
    # already initialized in a development process before an environment change.
    if os.getenv("SCHOOL_ENV", "").lower() == "production":
        return False
    if _collection is not None:
        return True
    try:
        import chromadb
        _model = _embedder()
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
        school_id = record.get("school_id", 1)
        if not isinstance(school_id, int) or isinstance(school_id, bool) or school_id < 1:
            raise ValueError("A valid school_id is required for indexing")
        metadata = {"school_id": school_id,
                    "source": str(record.get("source", "School information"))[:200],
                    "topic": str(record.get("topic", "Document"))[:200]}
        for i, chunk in enumerate(chunk_text(str(record.get("text", "")))):
            docs.append(chunk)
            # Tenant and metadata are part of identity/cache invalidation, even
            # when the text is unchanged or two schools use the same source ID.
            identity = json.dumps([school_id, str(record.get("id")), i, chunk,
                                   metadata["source"], metadata["topic"]],
                                  ensure_ascii=False, separators=(",", ":"))
            ids.append(hashlib.sha256(identity.encode()).hexdigest()[:32])
            metadatas.append(metadata.copy())
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

def _strip_headings(text: str) -> str:
    """Remove Markdown headings, which chunking flattens into the running text.

    A heading is the text after a "#" marker up to the first capitalised word that
    follows a lowercase word (or follows a one-word heading), e.g.
    "## Lunch and snacks The canteen..." -> "The canteen...".
    """
    parts = re.split(r"\s*#{1,6}\s+", " ".join(text.split()))
    kept = [parts[0]]
    for segment in parts[1:]:
        if not re.search(r"[.!?]", segment):
            continue  # a heading with no body before the next heading, e.g. a document title
        words = segment.split(" ")
        cut = len(words)
        for i in range(1, len(words)):
            if words[i][:1].isupper() and (i == 1 or words[i - 1][:1].islower()):
                cut = i
                break
        kept.append(" ".join(words[cut:]))
    return " ".join(p for p in kept if p)


def _sentences(text: str) -> list[str]:
    """Complete, readable sentences from a passage (no headings, bullets or cut-off fragments)."""
    prose = re.sub(r"(^|\s)[-*•]\s+", " ", _strip_headings(text))
    sentences = (s.strip() for s in re.split(r"(?<=[.!?])\s+", prose))
    return [s for s in sentences if len(s) >= 20 and re.match(r"[A-Z0-9]", s) and s[-1] in ".!?"]


def best_sentences(question: str, passages: list[str], limit: int = 2) -> str:
    """Quote the sentences that best answer the question, instead of whole chunks.

    Used when no local LLM is configured. It only selects text from the approved
    passages; it never rewrites or adds anything.
    """
    candidates = []
    for passage in passages:
        for sentence in _sentences(passage):
            if sentence not in candidates:
                candidates.append(sentence)
    if not candidates:
        return ""
    scores = None
    if _load():
        try:
            vectors = _model.encode([question] + candidates, normalize_embeddings=True)
            scores = [float(vectors[0] @ v) for v in vectors[1:]]
        except Exception:
            scores = None
    if scores is None:
        words = {w.rstrip("s") for w in re.findall(r"[a-z]{3,}", question.lower())}
        scores = [len(words & {w.rstrip("s") for w in re.findall(r"[a-z]{3,}", s.lower())}) for s in candidates]
    ranked = sorted(range(len(candidates)), key=lambda i: scores[i], reverse=True)
    top = scores[ranked[0]]
    # Add further sentences only when they are nearly as relevant as the best one.
    chosen = [i for i in ranked[:limit] if i == ranked[0] or (top > 0 and scores[i] >= 0.94 * top)]
    return " ".join(candidates[i] for i in chosen)


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
            # Defense in depth: never trust the vector backend's metadata filter alone.
            if metadata.get("school_id") != school_id:
                continue
            distance = (result.get("distances") or [[]])[0][i]
            output.append({"text": text, "source": metadata.get("source", "School information"),
                           "topic": metadata.get("topic", "Document"), "distance": distance})
        return output
    except Exception:
        return []
