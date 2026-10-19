"""Unpatched optional vector dependencies must not run in production."""
from app import rag


def test_rag_disabled_in_production_even_with_cached_collection(monkeypatch):
    monkeypatch.setenv("SCHOOL_ENV", "production")
    monkeypatch.setattr(rag, "_collection", object())
    assert rag.enabled() is False
    assert rag.rebuild([{"id": "example", "text": "private school data"}]) is False
    assert rag.search("private school data", school_id=1) == []


def test_rag_production_gate_does_not_import_chromadb(monkeypatch):
    monkeypatch.setenv("SCHOOL_ENV", "production")
    monkeypatch.setattr(rag, "_collection", None)
    monkeypatch.setattr(rag, "_model", None)
    assert rag.enabled() is False
