"""Real backup/restore acceptance for migration history and runtime credentials."""
from contextlib import contextmanager
import uuid
from urllib.parse import urlsplit, urlunsplit

import pytest


@contextmanager
def empty_restore_database(dsn):
    import psycopg
    from psycopg import sql

    parts = urlsplit(dsn)
    name = "school_restore_" + uuid.uuid4().hex
    admin = urlunsplit(parts._replace(path="/postgres"))
    target = urlunsplit(parts._replace(path="/" + name))
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        yield target
    finally:
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def test_versioned_restore_retains_history_and_reprovisioned_runtime_access(
    postgres_empty_database, postgres_runtime_login
):
    import psycopg
    from scripts.postgres_migrations import migrate
    from scripts.postgres_restore_verify import verify
    from scripts.postgres_data_integrity import verify_data

    source = postgres_empty_database
    migrate(source)
    with psycopg.connect(source) as connection:
        connection.execute("INSERT INTO schools(slug,name) VALUES('restored-school','Fictional school')")
    with empty_restore_database(source) as restored:
        assert verify(source, restored)["schools"] == 1
        assert migrate(restored) == 0
        with postgres_runtime_login(restored) as runtime:
            with psycopg.connect(runtime) as connection:
                assert connection.execute("SELECT name FROM schools").fetchone()[0] == "Fictional school"
                connection.execute("UPDATE schools SET name='Runtime update' WHERE slug='restored-school'")
                assert connection.execute("SELECT name FROM schools").fetchone()[0] == "Runtime update"
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    connection.execute("DELETE FROM school_schema_migrations")
        # The rejected ledger write rolls back the preceding test-only update.
        with psycopg.connect(restored) as connection:
            connection.execute("UPDATE school_schema_migrations SET checksum='tampered' WHERE version='001'")
        with psycopg.connect(source) as original, psycopg.connect(restored) as copied:
            with pytest.raises(RuntimeError, match="migration-history data mismatch"):
                verify_data(original, copied)
        with psycopg.connect(restored) as connection:
            connection.execute("DROP TABLE school_schema_migrations")
        with psycopg.connect(source) as original, psycopg.connect(restored) as copied:
            with pytest.raises(RuntimeError, match="migration-history presence mismatch"):
                verify_data(original, copied)
