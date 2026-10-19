"""PostgreSQL schema smoke test; does not modify the existing SQLite application."""
import os
from pathlib import Path

import pytest

SCHEMA=Path(__file__).resolve().parents[1]/"migrations"/"postgresql"/"001_initial.sql"


def test_schema_contains_tenant_scoped_uniqueness():
    sql=SCHEMA.read_text()
    assert "UNIQUE(school_id,policy_key,version)" in sql
    assert "UNIQUE(school_id,username)" in sql
    assert "CREATE TABLE IF NOT EXISTS escalations" in sql
    assert "school_id BIGINT NOT NULL REFERENCES schools(id)" in sql


def test_postgres_schema_against_ephemeral_database():
    url=os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("TEST_POSTGRES_URL not set")
    import psycopg
    with psycopg.connect(url,autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA.read_text())
            cur.execute((SCHEMA.parent/"002_revoke_sessions_on_school_disable.sql").read_text())
            cur.execute("INSERT INTO schools(slug,name) VALUES('school-a','School A'),('school-b','School B') RETURNING id")
            ids=[r[0] for r in cur.fetchall()]
            for school_id in ids:
                cur.execute("""INSERT INTO policy_versions(school_id,policy_key,version,title,filename,content,effective_date)
                               VALUES(%s,'fees',1,'Fees','fees.txt','Demo policy','2026-01-01')""",(school_id,))
            from scripts.postgres_bootstrap import validate
            assert validate(url) is True
            cur.execute("ALTER TABLE parent_notification_reads DISABLE TRIGGER trg_parent_notification_school")
            with pytest.raises(RuntimeError,match="tenant-isolation trigger"):
                validate(url)
            cur.execute("ALTER TABLE parent_notification_reads ENABLE TRIGGER trg_parent_notification_school")
            assert validate(url) is True
            cur.execute("SELECT COUNT(*) FROM policy_versions WHERE policy_key='fees'")
            assert cur.fetchone()[0]==2
            with pytest.raises(psycopg.errors.UniqueViolation):
                cur.execute("""INSERT INTO policy_versions(school_id,policy_key,version,title,filename,content,effective_date)
                               VALUES(%s,'fees',1,'Duplicate','fees.txt','Demo','2026-01-01')""",(ids[0],))
