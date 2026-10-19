"""Real PostgreSQL migration rollback, data fidelity, and pg_dump/pg_restore drill.

Uses disposable databases in CI; never touches a real school's database.
"""
import os
import uuid
from urllib.parse import urlsplit,urlunsplit
import pytest


def _dsn_with_db(dsn,name):
    parts=urlsplit(dsn)
    return urlunsplit((parts.scheme,parts.netloc,"/"+name,parts.query,parts.fragment))


def test_migration_and_restore_against_disposable_postgres(tmp_path,monkeypatch):
    dsn=os.getenv("TEST_POSTGRES_URL")
    if not dsn:pytest.skip("Requires isolated PostgreSQL 16")
    import psycopg
    from app import main
    from scripts.postgres_bootstrap import initialize_empty
    from scripts.migrate_sqlite_to_postgres import migrate,TABLES
    from scripts.verify_postgres_restore import verify
    from scripts.postgres_restore_verify import verify as verify_row_counts
    db_file=tmp_path/"source.db"
    monkeypatch.setattr(main,"DB",str(db_file))
    main.setup()
    with main.db() as c:
        c.execute("INSERT INTO staff_accounts(school_id,username,display_name,salt,password_hash,role) VALUES(1,'teacher','Teacher','salt','hash','staff')")
        c.execute("INSERT INTO escalations(school_id,question) VALUES(1,'What is the next school event?')")
    suffix=uuid.uuid4().hex[:12]
    target="school_migrate_"+suffix
    restored="school_restore_"+suffix
    verified="school_verify_"+suffix
    admin=_dsn_with_db(dsn,"postgres")
    with psycopg.connect(admin,autocommit=True) as root:
        root.execute(f'CREATE DATABASE "{target}"')
        root.execute(f'CREATE DATABASE "{restored}"')
        root.execute(f'CREATE DATABASE "{verified}"')
    try:
        target_dsn=_dsn_with_db(dsn,target)
        restore_dsn=_dsn_with_db(dsn,restored)
        verify_dsn=_dsn_with_db(dsn,verified)
        initialize_empty(target_dsn)
        dry_counts=migrate(db_file,target_dsn,dry_run=True)
        assert dry_counts["schools"]==1
        with psycopg.connect(target_dsn) as c:
            assert c.execute("SELECT COUNT(*) FROM schools").fetchone()[0]==0
        applied=migrate(db_file,target_dsn,dry_run=False)
        assert applied==dry_counts
        with psycopg.connect(target_dsn) as c:
            for table,count in applied.items():
                assert c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]==count
            assert c.execute("SELECT question FROM escalations").fetchone()[0]=="What is the next school event?"
            assert c.execute("SELECT username FROM staff_accounts").fetchone()[0]=="teacher"
        assert verify(target_dsn,restore_dsn)
        counts=verify_row_counts(target_dsn,verify_dsn)
        assert counts["schools"]==applied["schools"]
        assert counts["staff_accounts"]==applied["staff_accounts"]
        with pytest.raises(ValueError,match="same database|must differ"):
            verify_row_counts(target_dsn,target_dsn)
    finally:
        with psycopg.connect(admin,autocommit=True) as root:
            for name in (verified,restored,target):
                root.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
