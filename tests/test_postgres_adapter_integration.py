"""Exercise the actual PostgreSQL connection adapter against PostgreSQL 16.

These tests intentionally do not enable the FastAPI PostgreSQL runtime: app setup
and several feature queries still require conversion.
"""
import os
import pytest


def test_postgres_adapter_insert_read_rollback():
    dsn=os.getenv("TEST_POSTGRES_URL")
    if not dsn:
        pytest.skip("Requires isolated TEST_POSTGRES_URL")
    from app.postgres_adapter import connect
    from scripts.postgres_bootstrap import validate
    assert validate(dsn)
    with pytest.raises(RuntimeError,match="rollback test"):
        with connect(dsn) as c:
            row=c.execute("INSERT INTO schools(slug,name) VALUES(?,?) RETURNING id",
                          ("adapter-rollback-check","Adapter Rollback Check")).fetchone()
            assert isinstance(row["id"],int)
            result=c.execute("SELECT name FROM schools WHERE id=?",(row["id"],)).fetchone()
            assert result["name"]=="Adapter Rollback Check"
            raise RuntimeError("rollback test")
    with connect(dsn) as c:
        assert c.execute("SELECT COUNT(*) AS count FROM schools WHERE slug=?",
                         ("adapter-rollback-check",)).fetchone()["count"]==0


def test_postgres_adapter_rejects_sqlite_only_sql():
    dsn=os.getenv("TEST_POSTGRES_URL")
    if not dsn:
        pytest.skip("Requires isolated TEST_POSTGRES_URL")
    from app.postgres_adapter import connect
    with connect(dsn) as c:
        with pytest.raises(NotImplementedError):
            c.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(NotImplementedError):
            c.execute("INSERT OR IGNORE INTO schools(slug,name) VALUES(?,?)",("x","y"))
