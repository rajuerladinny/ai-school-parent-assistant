"""Real local embedding smoke test. Requires requirements-rag.txt and model download.

Usage: python scripts/smoke_rag.py
No OpenAI API key or paid service is needed.
"""
import os
import tempfile
from app import rag

def main():
    with tempfile.TemporaryDirectory() as directory:
        os.environ["RAG_VECTOR_PATH"] = directory
        rag._client = rag._collection = rag._model = None
        rag._last_fingerprint = None
        assert rag.enabled(), "Install requirements-rag.txt and download the embedding model"
        assert rag.rebuild([
            {"id": "library", "topic": "Library", "source": "Sample library policy",
             "text": "The school library opens at 9 AM and closes at 2 PM on weekdays."},
            {"id": "fees", "topic": "Fees", "source": "Sample fee policy",
             "text": "Ask the school accounts office for tuition payment methods."}
        ]), "Indexing failed"
        matches = rag.search("At what time does the school library close?")
        assert matches, "No semantic matches returned"
        print("Top source:", matches[0]["source"])
        print("Distance:", matches[0]["distance"])
        print("Pass: local model loaded, vectors indexed and retrieved.")
if __name__ == "__main__":
    main()
