"""PostgreSQL schema smoke test; does not modify the existing SQLite application."""
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

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
    # Never write fixtures to the shared TEST_POSTGRES_URL database.
    # Create an isolated database and always remove it, including on failure.
    from scripts.postgres_bootstrap import initialize_empty
    parts = urlsplit(url)
    name = "school_schema_" + uuid.uuid4().hex[:12]
    admin = urlunsplit((parts.scheme, parts.netloc, "/postgres", parts.query, parts.fragment))
    target = urlunsplit((parts.scheme, parts.netloc, "/" + name, parts.query, parts.fragment))
    with psycopg.connect(admin, autocommit=True) as root:
        root.execute(f'CREATE DATABASE "{name}"')
    try:
        initialize_empty(target)
        with psycopg.connect(target, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO schools(slug,name) VALUES('school-a','School A'),('school-b','School B') RETURNING id")
                ids=[r[0] for r in cur.fetchall()]
                for school_id in ids:
                    cur.execute("""INSERT INTO policy_versions(school_id,policy_key,version,title,filename,content,effective_date)
                                   VALUES(%s,'fees',1,'Fees','fees.txt','Demo policy','2026-01-01')""",(school_id,))
                from scripts.postgres_bootstrap import validate
                assert validate(target) is True
                # Both parent and staff tokens must be destroyed on school disable,
                # and must not reappear after the school is reactivated.
                cur.execute("""INSERT INTO parent_accounts(school_id,username,display_name,salt,password_hash)
                    VALUES(%s,'pg_revoke_parent','Parent','salt','hash') RETURNING id""",(ids[0],))
                parent_id=cur.fetchone()[0]
                cur.execute("""INSERT INTO staff_accounts(school_id,username,display_name,salt,password_hash,role)
                    VALUES(%s,'pg_revoke_staff','Staff','salt','hash','staff') RETURNING id""",(ids[0],))
                staff_id=cur.fetchone()[0]
                cur.execute("INSERT INTO parent_sessions(token_hash,parent_id,expires_at) VALUES('pg_parent_token',%s,NOW()+INTERVAL '1 hour')",(parent_id,))
                cur.execute("INSERT INTO staff_sessions(token_hash,staff_id,expires_at) VALUES('pg_staff_token',%s,NOW()+INTERVAL '1 hour')",(staff_id,))
                cur.execute("UPDATE schools SET active=FALSE WHERE id=%s",(ids[0],))
                cur.execute("UPDATE schools SET active=TRUE WHERE id=%s",(ids[0],))
                cur.execute("SELECT COUNT(*) FROM parent_sessions WHERE parent_id=%s",(parent_id,))
                assert cur.fetchone()[0]==0
                cur.execute("SELECT COUNT(*) FROM staff_sessions WHERE staff_id=%s",(staff_id,))
                assert cur.fetchone()[0]==0
                cur.execute("ALTER TABLE schools DISABLE TRIGGER trg_revoke_school_sessions")
                with pytest.raises(RuntimeError,match="session-revocation trigger"):
                    validate(target)
                cur.execute("ALTER TABLE schools ENABLE TRIGGER trg_revoke_school_sessions")
                assert validate(target) is True
                # Restored trigger must actively revoke newly issued sessions.
                cur.execute("INSERT INTO parent_sessions(token_hash,parent_id,expires_at) VALUES('pg_parent_token_restored',%s,NOW()+INTERVAL '1 hour')",(parent_id,))
                cur.execute("UPDATE schools SET active=FALSE WHERE id=%s",(ids[0],))
                cur.execute("SELECT COUNT(*) FROM parent_sessions WHERE parent_id=%s",(parent_id,))
                assert cur.fetchone()[0]==0
                cur.execute("UPDATE schools SET active=TRUE WHERE id=%s",(ids[0],))
                cur.execute("ALTER TABLE parent_notification_reads DISABLE TRIGGER trg_parent_notification_school")
                with pytest.raises(RuntimeError,match="tenant-isolation trigger"):
                    validate(target)
                cur.execute("ALTER TABLE parent_notification_reads ENABLE TRIGGER trg_parent_notification_school")
                assert validate(target) is True
                cur.execute("SELECT COUNT(*) FROM policy_versions WHERE policy_key='fees'")
                assert cur.fetchone()[0]==2
                with pytest.raises(psycopg.errors.UniqueViolation):
                    cur.execute("""INSERT INTO policy_versions(school_id,policy_key,version,title,filename,content,effective_date)
                                   VALUES(%s,'fees',1,'Duplicate','fees.txt','Demo','2026-01-01')""",(ids[0],))
    finally:
        with psycopg.connect(admin, autocommit=True) as root:
            root.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
