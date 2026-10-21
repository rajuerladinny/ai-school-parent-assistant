"""Versioned migrations commit their schema and ledger together."""
import shutil

import pytest

from scripts.postgres_migrations import DIRECTORY, migrate


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
