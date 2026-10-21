"""Exercise the actual PostgreSQL connection adapter against PostgreSQL 16.

These tests intentionally do not enable the FastAPI PostgreSQL runtime: app setup
and several feature queries still require conversion.
"""
import pytest


def test_postgres_adapter_insert_read_rollback(postgres_database):
    dsn=postgres_database
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


def test_postgres_adapter_rejects_sqlite_only_sql(postgres_database):
    dsn=postgres_database
    from app.postgres_adapter import connect
    with connect(dsn) as c:
        with pytest.raises(NotImplementedError):
            c.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(NotImplementedError):
            c.execute("INSERT OR IGNORE INTO schools(slug,name) VALUES(?,?)",("x","y"))


def test_postgres_adapter_explicit_commit_and_rollback(postgres_database):
    dsn=postgres_database
    from app.postgres_adapter import connect
    slug="adapter-transaction-methods"
    with connect(dsn) as c:
        c.execute("DELETE FROM schools WHERE slug=?",(slug,))
        c.execute("INSERT INTO schools(slug,name) VALUES(?,?)",(slug,"Temporary"))
        c.rollback()
        assert c.execute("SELECT COUNT(*) AS n FROM schools WHERE slug=?",(slug,)).fetchone()["n"]==0
        c.execute("INSERT INTO schools(slug,name) VALUES(?,?)",(slug,"Committed"))
        c.commit()
    with connect(dsn) as c:
        assert c.execute("SELECT COUNT(*) AS n FROM schools WHERE slug=?",(slug,)).fetchone()["n"]==1
        c.execute("DELETE FROM schools WHERE slug=?",(slug,))
