"""Real PostgreSQL migration rollback, data fidelity, and pg_dump/pg_restore drill.

Uses disposable databases in CI; never touches a real school's database.
"""
import os
import uuid
from urllib.parse import urlsplit,urlunsplit
import pytest


@pytest.fixture
def populated_sqlite(tmp_path, monkeypatch):
    """Exercise every migrated column with fictional data, offsets, NULLs and flags."""
    from app import main
    from scripts.migrate_sqlite_to_postgres import TABLES
    path = tmp_path / "source # school.db"
    monkeypatch.setenv("SCHOOL_DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(main, "DB", str(path))
    main.setup()
    stamp = "2026-02-03T11:22:33.123456+05:30"
    records = {
        "parent_accounts": (101,1,"parent","Fictional Parent","salt","parent hash",1,stamp),
        "knowledge": (301,1,"Fees – FAQ","Fictional answer\nwith a second line","Handbook",0),
        "documents": (401,1,"policy.txt","Fictional document","Text with 'quotes' and Unicode ₹",stamp,1),
        "policy_versions": (501,1,"fees",3,"Fees","fees.txt","Fictional approved policy","approved","2026-02-04",stamp,None),
        "staff_accounts": (201,1,"teacher","Fictional Teacher","salt","staff hash","staff",0,stamp),
        "escalations": (601,1,101,"Fictional question?","resolved","teacher","Verified fictional reply",stamp,stamp,stamp),
        "escalation_events": (701,601,"resolved",None,stamp),
        "knowledge_conflicts": (801,501,"faq",301,"resolved",stamp,stamp),
        "parent_notification_reads": (101,501,"2026-02-03 05:52:33.123456"),
        "parent_sessions": ("fictional-parent-token-hash",101,"2030-01-01T00:00:00Z"),
        "staff_sessions": ("fictional-staff-token-hash",201,"2030-01-01T00:00:00+00:00"),
    }
    with main.db() as connection:
        connection.execute("INSERT INTO schools(id,slug,name,active) VALUES(2,'inactive','Inactive fictional school',0)")
        for table, values in records.items():
            columns = TABLES[table]
            connection.execute(
                f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", values)
    return path


def sequence_states(dsn):
    import psycopg
    from psycopg import sql
    from scripts.migrate_sqlite_to_postgres import TABLES
    states = {}
    with psycopg.connect(dsn) as connection:
        for table, columns in TABLES.items():
            if "id" not in columns:
                continue
            schema, name = connection.execute(
                "SELECT n.nspname,c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE c.oid=pg_get_serial_sequence(%s,'id')::regclass", (table,)).fetchone()
            states[table] = connection.execute(sql.SQL("SELECT last_value,is_called FROM {}.{}").format(
                sql.Identifier(schema), sql.Identifier(name))).fetchone()
    return states


def test_migration_dry_run_preserves_sequences(populated_sqlite, postgres_database):
    from scripts.migrate_sqlite_to_postgres import migrate
    before = sequence_states(postgres_database)
    migrate(populated_sqlite, postgres_database, dry_run=True)
    assert sequence_states(postgres_database) == before


def test_sqlite_migration_can_adopt_version_history_without_changing_records(populated_sqlite, postgres_database):
    import psycopg
    from scripts.migrate_sqlite_to_postgres import migrate, TABLES
    from scripts.postgres_migrations import adopt_existing, migrate as upgrade

    migrate(populated_sqlite, postgres_database, dry_run=False)
    with psycopg.connect(postgres_database) as connection:
        before = {table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in TABLES}
    sequences = sequence_states(postgres_database)
    assert adopt_existing(postgres_database) == 2
    assert upgrade(postgres_database) == 0
    with psycopg.connect(postgres_database) as connection:
        assert {table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in TABLES} == before
    assert sequence_states(postgres_database) == sequences


def test_migration_rejects_invalid_boolean(populated_sqlite, postgres_database):
    import sqlite3
    from scripts.migrate_sqlite_to_postgres import migrate
    with sqlite3.connect(populated_sqlite) as source:
        source.execute("UPDATE schools SET active=2 WHERE id=2")
    with pytest.raises(ValueError, match="boolean"):
        migrate(populated_sqlite, postgres_database, dry_run=False)


def test_migration_rejects_silent_content_changes(populated_sqlite, postgres_database):
    import psycopg
    from scripts.migrate_sqlite_to_postgres import migrate
    with psycopg.connect(postgres_database) as connection:
        connection.execute("""CREATE FUNCTION alter_fixture_content() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN NEW.content := 'Unexpected content change'; RETURN NEW; END $$""")
        connection.execute("CREATE TRIGGER alter_fixture_content BEFORE INSERT ON documents "
                           "FOR EACH ROW EXECUTE FUNCTION alter_fixture_content()")
    with pytest.raises(ValueError, match="Data mismatch.*documents"):
        migrate(populated_sqlite, postgres_database, dry_run=False)


def test_migration_refuses_unhandled_legacy_records(populated_sqlite, postgres_database):
    import sqlite3
    from scripts.migrate_sqlite_to_postgres import migrate
    with sqlite3.connect(populated_sqlite) as source:
        source.execute("INSERT INTO notification_subscribers(token,label) VALUES('fictional-legacy-token','Fictional legacy parent')")
    with pytest.raises(ValueError, match="Unmigrated source table"):
        migrate(populated_sqlite, postgres_database, dry_run=False)


def test_migration_refuses_unhandled_columns(populated_sqlite, postgres_database):
    import sqlite3
    from scripts.migrate_sqlite_to_postgres import migrate
    with sqlite3.connect(populated_sqlite) as source:
        source.execute("ALTER TABLE documents ADD COLUMN internal_note TEXT")
        source.execute("UPDATE documents SET internal_note='Fictional note that must not disappear'")
    with pytest.raises(ValueError, match="Unmigrated source columns in documents"):
        migrate(populated_sqlite, postgres_database, dry_run=False)


def test_migration_rejects_cross_school_parent_relationship(populated_sqlite, postgres_database):
    import sqlite3
    from scripts.migrate_sqlite_to_postgres import migrate
    with sqlite3.connect(populated_sqlite) as source:
        source.execute("INSERT INTO parent_accounts(id,school_id,username,display_name,salt,password_hash) "
                       "VALUES(102,2,'otherparent','Fictional other parent','salt','hash')")
        source.execute("UPDATE escalations SET parent_id=102")
    with pytest.raises(ValueError, match="Cross-school tenant relationship"):
        migrate(populated_sqlite, postgres_database, dry_run=False)


def _dsn_with_db(dsn,name):
    parts=urlsplit(dsn)
    return urlunsplit((parts.scheme,parts.netloc,"/"+name,parts.query,parts.fragment))


def test_migration_and_restore_against_disposable_postgres(populated_sqlite):
    dsn=os.getenv("TEST_POSTGRES_URL")
    if not dsn:pytest.skip("Requires isolated PostgreSQL 16")
    import psycopg
    import hashlib
    from datetime import datetime, timezone
    from scripts.postgres_bootstrap import initialize_empty
    from scripts.migrate_sqlite_to_postgres import migrate,TABLES
    from scripts.verify_postgres_restore import verify
    from scripts.postgres_restore_verify import verify as verify_row_counts
    db_file=populated_sqlite
    source_hash=hashlib.sha256(db_file.read_bytes()).hexdigest()
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
        assert dry_counts["schools"]==2
        assert all(count > 0 for count in dry_counts.values())
        with psycopg.connect(target_dsn) as c:
            assert c.execute("SELECT COUNT(*) FROM schools").fetchone()[0]==0
        applied=migrate(db_file,target_dsn,dry_run=False)
        assert applied==dry_counts
        with psycopg.connect(target_dsn) as c:
            for table,count in applied.items():
                assert c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]==count
            assert c.execute("SELECT question,parent_id FROM escalations").fetchone()==("Fictional question?",101)
            assert c.execute("SELECT username FROM staff_accounts").fetchone()[0]=="teacher"
            assert c.execute("SELECT created_at FROM parent_accounts").fetchone()[0] == datetime(
                2026,2,3,5,52,33,123456,tzinfo=timezone.utc)
            assert c.execute("SELECT read_at FROM parent_notification_reads").fetchone()[0] == datetime(
                2026,2,3,5,52,33,123456,tzinfo=timezone.utc)
            assert c.execute("SELECT enabled FROM staff_accounts").fetchone()[0] is False
            assert c.execute("SELECT active FROM schools WHERE id=2").fetchone()[0] is False
            assert c.execute("SELECT content FROM documents").fetchone()[0] == "Text with 'quotes' and Unicode ₹"
            assert c.execute("SELECT reviewed_at FROM policy_versions").fetchone()[0] is None
            for table, columns in TABLES.items():
                if "id" in columns:
                    maximum=c.execute(f"SELECT MAX(id) FROM {table}").fetchone()[0]
                    next_id=c.execute("SELECT nextval(pg_get_serial_sequence(%s,'id'))", (table,)).fetchone()[0]
                    assert next_id == maximum+1
        assert hashlib.sha256(db_file.read_bytes()).hexdigest() == source_hash
        assert verify(target_dsn,restore_dsn)
        counts=verify_row_counts(target_dsn,verify_dsn)
        assert counts["schools"]==applied["schools"]
        assert counts["staff_accounts"]==applied["staff_accounts"]
        from scripts.postgres_data_integrity import verify_data
        with psycopg.connect(target_dsn) as source, psycopg.connect(verify_dsn) as copied:
            copied.execute("UPDATE documents SET content='Wrong content with the same row count'")
            with pytest.raises(RuntimeError,match="Restore data mismatch in documents"):
                verify_data(source,copied)
            copied.execute("UPDATE documents SET content=%s", ("Text with 'quotes' and Unicode ₹",))
            copied.execute("SELECT nextval(pg_get_serial_sequence('documents','id'))")
            with pytest.raises(RuntimeError,match="Restore sequence mismatch in documents"):
                verify_data(source,copied)
        with pytest.raises(ValueError,match="same database|must differ"):
            verify_row_counts(target_dsn,target_dsn)
    finally:
        with psycopg.connect(admin,autocommit=True) as root:
            for name in (verified,restored,target):
                root.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_late_migration_failure_rolls_back_and_can_retry(populated_sqlite, postgres_database):
    import sqlite3
    import psycopg
    from scripts.migrate_sqlite_to_postgres import migrate, TABLES
    before=sequence_states(postgres_database)
    with sqlite3.connect(populated_sqlite) as source:
        source.execute("UPDATE staff_sessions SET expires_at='invalid timestamp'")
    with pytest.raises(ValueError):
        migrate(populated_sqlite,postgres_database,dry_run=False)
    with psycopg.connect(postgres_database) as connection:
        for table in TABLES:
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert sequence_states(postgres_database) == before
    with sqlite3.connect(populated_sqlite) as source:
        source.execute("UPDATE staff_sessions SET expires_at='2030-01-01T00:00:00+00:00'")
    counts=migrate(populated_sqlite,postgres_database,dry_run=False)
    assert all(value > 0 for value in counts.values())
    applied_sequences=sequence_states(postgres_database)
    with pytest.raises(ValueError,match="must be empty"):
        migrate(populated_sqlite,postgres_database,dry_run=False)
    assert sequence_states(postgres_database) == applied_sequences
    with psycopg.connect(postgres_database) as connection:
        for table, count in counts.items():
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == count
