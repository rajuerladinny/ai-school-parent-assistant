"""PostgreSQL FastAPI connection routing and startup safety tests."""
import pytest
from app import main


def test_postgres_db_routes_to_adapter(monkeypatch):
    sentinel=object()
    from app import postgres_adapter
    monkeypatch.setenv("SCHOOL_DATABASE_BACKEND","postgres")
    monkeypatch.setenv("SCHOOL_POSTGRES_DSN","postgresql://user:pass@localhost/school")
    def connect(dsn):
        assert dsn=="postgresql://user:pass@localhost/school"
        return sentinel
    monkeypatch.setattr(postgres_adapter,"connect",connect)
    assert main.db() is sentinel


def test_sqlite_backend_still_uses_sqlite(monkeypatch,tmp_path):
    monkeypatch.setenv("SCHOOL_DATABASE_BACKEND","sqlite")
    monkeypatch.setattr(main,"DB",str(tmp_path/"test.db"))
    with main.db() as c:
        assert c.execute("PRAGMA foreign_keys").fetchone()[0]==1


def test_postgres_startup_fails_closed_before_schema_or_index(monkeypatch):
    monkeypatch.setenv("SCHOOL_DATABASE_BACKEND","postgres")
    monkeypatch.setenv("SCHOOL_POSTGRES_DSN","postgresql://user:pass@localhost/school")
    monkeypatch.setenv("SCHOOL_POSTGRES_RUNTIME_READY","1")
    monkeypatch.setattr(main,"setup",lambda:pytest.fail("SQLite setup must not run"))
    monkeypatch.setattr(main,"rebuild_index",lambda:pytest.fail("Index must not run before validation"))
    with pytest.raises(RuntimeError,match="runtime adapter integration is not complete"):
        main.startup()
