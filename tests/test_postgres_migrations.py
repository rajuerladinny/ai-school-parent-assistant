"""Versioned migrations commit their schema and ledger together."""
import shutil

import pytest

from scripts.postgres_migrations import DIRECTORY, migrate


def test_adoption_preserves_all_data_and_sequence_state(postgres_database):
    import psycopg
    from scripts.postgres_migrations import adopt_existing
    from scripts.migrate_sqlite_to_postgres import TABLES
    from scripts.postgres_data_integrity import sequence_state

    dsn = postgres_database
    with psycopg.connect(dsn) as connection:
        school = connection.execute("INSERT INTO schools(slug,name) VALUES('adopt','Fictional school') RETURNING id").fetchone()[0]
        connection.execute("INSERT INTO knowledge(school_id,topic,answer,source) VALUES(%s,'Bus','Fictional answer','Handbook')", (school,))
    def snapshot():
        with psycopg.connect(dsn) as connection:
            rows = {table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in TABLES}
            sequences = {table: sequence_state(connection, table) for table, columns in TABLES.items() if "id" in columns}
        return rows, sequences
    before = snapshot()
    assert adopt_existing(dsn) == 2
    assert snapshot() == before
    assert migrate(dsn) == 0
    with pytest.raises(RuntimeError, match="history already exists"):
        adopt_existing(dsn)


@pytest.mark.parametrize("drift", [
    "ALTER TABLE knowledge ALTER COLUMN answer DROP NOT NULL",
    "ALTER TABLE policy_versions DROP CONSTRAINT policy_versions_school_id_policy_key_version_key",
    "ALTER TABLE schools DISABLE TRIGGER trg_revoke_school_sessions",
    "CREATE OR REPLACE FUNCTION revoke_school_sessions_on_disable() RETURNS TRIGGER LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$",
    "ALTER SEQUENCE schools_id_seq INCREMENT BY 2",
    "CREATE TABLE unexpected_table(id INT)",
    "ALTER TABLE knowledge ADD COLUMN unexpected_column TEXT",
    "CREATE TYPE unexpected_type AS ENUM ('unexpected')",
    "CREATE RULE unexpected_rule AS ON UPDATE TO knowledge DO INSTEAD NOTHING",
])
def test_adoption_rejects_schema_drift_without_ledger_or_reference_objects(postgres_database, drift):
    import psycopg
    from scripts.postgres_migrations import adopt_existing

    with psycopg.connect(postgres_database) as connection:
        connection.execute(drift)
    with pytest.raises(RuntimeError, match="differs from reviewed baseline"):
        adopt_existing(postgres_database)
    with psycopg.connect(postgres_database) as connection:
        assert connection.execute("SELECT to_regclass('public.school_schema_migrations')").fetchone()[0] is None
        assert connection.execute("SELECT COUNT(*) FROM pg_namespace WHERE nspname LIKE 'school_baseline_%'").fetchone()[0] == 0


def test_adoption_refuses_empty_database(postgres_empty_database):
    from scripts.postgres_migrations import adopt_existing
    with pytest.raises(RuntimeError, match="requires an existing schema"):
        adopt_existing(postgres_empty_database)


def test_fresh_migration_is_repeatable_and_valid(postgres_empty_database):
    import psycopg
    from scripts.postgres_bootstrap import validate

    dsn = postgres_empty_database
    assert migrate(dsn) == 2
    assert migrate(dsn) == 0
    assert validate(dsn)
    with psycopg.connect(dsn) as connection:
        assert connection.execute(
            "SELECT version FROM school_schema_migrations ORDER BY version"
        ).fetchall() == [("001",), ("002",)]


def test_migration_failure_rolls_back_schema_and_ledger(postgres_empty_database, tmp_path):
    import psycopg

    for path in DIRECTORY.glob("*.sql"):
        shutil.copyfile(path, tmp_path / path.name)
    (tmp_path / "003_failure.sql").write_text(
        "CREATE TABLE rollback_probe(id INT); SELECT * FROM nonexistent_probe;", encoding="utf-8"
    )
    with pytest.raises(psycopg.errors.UndefinedTable):
        migrate(postgres_empty_database, tmp_path)
    with psycopg.connect(postgres_empty_database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM pg_tables WHERE schemaname='public'").fetchone()[0] == 0
    assert migrate(postgres_empty_database) == 2


def test_changed_or_missing_history_is_rejected(postgres_empty_database, tmp_path):
    import psycopg

    migrate(postgres_empty_database)
    for path in DIRECTORY.glob("*.sql"):
        shutil.copyfile(path, tmp_path / path.name)
    first = tmp_path / "001_initial.sql"
    first.write_text(first.read_text(encoding="utf-8") + "\n-- modified\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        migrate(postgres_empty_database, tmp_path)
    first.unlink()
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        migrate(postgres_empty_database, tmp_path)
    with psycopg.connect(postgres_empty_database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM school_schema_migrations").fetchone()[0] == 2


def test_untracked_existing_schema_is_not_adopted(postgres_database):
    with pytest.raises(RuntimeError, match="existing untracked schema"):
        migrate(postgres_database)


def test_failed_upgrade_preserves_previous_version(postgres_empty_database, tmp_path):
    import psycopg

    migrate(postgres_empty_database)
    for path in DIRECTORY.glob("*.sql"):
        shutil.copyfile(path, tmp_path / path.name)
    (tmp_path / "003_failure.sql").write_text(
        "ALTER TABLE schools ADD COLUMN rollback_probe INT; SELECT * FROM missing_upgrade_probe;",
        encoding="utf-8",
    )
    with pytest.raises(psycopg.errors.UndefinedTable):
        migrate(postgres_empty_database, tmp_path)
    with psycopg.connect(postgres_empty_database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM school_schema_migrations").fetchone()[0] == 2
        assert connection.execute("""SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name='schools' AND column_name='rollback_probe'""").fetchone()[0] == 0


def test_upgrade_preserves_data_and_concurrent_runners_apply_once(postgres_empty_database, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import psycopg
    from scripts.postgres_bootstrap import validate

    shutil.copyfile(DIRECTORY / "001_initial.sql", tmp_path / "001_initial.sql")
    assert migrate(postgres_empty_database, tmp_path) == 1
    with psycopg.connect(postgres_empty_database) as connection:
        connection.execute("INSERT INTO schools(slug,name) VALUES('upgrade-school','Fictional school')")
    shutil.copyfile(DIRECTORY / "002_revoke_sessions_on_school_disable.sql",
                    tmp_path / "002_revoke_sessions_on_school_disable.sql")
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: migrate(postgres_empty_database, tmp_path), range(2)))
    assert sorted(results) == [0, 1]
    assert validate(postgres_empty_database)
    with psycopg.connect(postgres_empty_database) as connection:
        assert connection.execute("SELECT name FROM schools WHERE slug='upgrade-school'").fetchone()[0] == "Fictional school"
