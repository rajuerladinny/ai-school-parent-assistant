"""Apply ordered PostgreSQL migrations atomically with a checksum ledger.

Existing untracked schemas require explicit structural adoption before upgrades.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import uuid

DIRECTORY = Path(__file__).resolve().parents[1] / "migrations" / "postgresql"


def _records(directory):
    files = sorted(directory.glob("[0-9][0-9][0-9]_*.sql"))
    versions = [path.name[:3] for path in files]
    if not files or len(set(versions)) != len(versions):
        raise RuntimeError("Migration versions must be present and unique")
    records, scripts = [], []
    for path in files:
        content = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        records.append((path.name[:3], path.name, hashlib.sha256(content.encode()).hexdigest()))
        scripts.append(re.sub(r"^(BEGIN|COMMIT);\s*$", "", content, flags=re.MULTILINE))
    return records, scripts


def _create_ledger(connection):
    connection.execute("""CREATE TABLE public.school_schema_migrations (
        version TEXT PRIMARY KEY, filename TEXT NOT NULL, checksum TEXT NOT NULL,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")


def adopt_existing(dsn):
    """Baseline only the exact known 001+002 schema; never replay SQL on user data."""
    import psycopg
    from psycopg import sql
    from scripts.postgres_schema_signature import signature

    records, scripts = _records(DIRECTORY)
    if [record[0] for record in records] != ["001", "002"]:
        raise RuntimeError("Adoption supports only the reviewed 001+002 baseline")
    reference = "school_baseline_" + uuid.uuid4().hex
    with psycopg.connect(dsn) as connection:
        connection.execute("SET LOCAL search_path TO public")
        connection.execute("SET LOCAL lock_timeout TO '5s'")
        connection.execute("SELECT pg_advisory_xact_lock(73421009)")
        if connection.execute("SELECT to_regclass('public.school_schema_migrations')").fetchone()[0]:
            raise RuntimeError("Migration history already exists; use the migration runner")
        # Maintenance-window operation: exclusive locks stabilize existing tables.
        tables = connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()
        if not tables:
            raise RuntimeError("Adoption requires an existing schema")
        for (table,) in sorted(tables):
            connection.execute(sql.SQL("LOCK TABLE public.{} IN ACCESS EXCLUSIVE MODE").format(sql.Identifier(table)))
        actual = signature(connection, "public")
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(reference)))
        connection.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(reference)))
        for script in scripts:
            connection.execute(script)
        expected = signature(connection, reference)
        if actual != expected:
            changed = ", ".join(key for key in expected if actual[key] != expected[key])
            raise RuntimeError("Existing schema differs from reviewed baseline: " + changed)
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(reference)))
        _create_ledger(connection)
        for record in records:
            connection.execute("INSERT INTO public.school_schema_migrations(version,filename,checksum) VALUES(%s,%s,%s)", record)
    return len(records)


def migrate(dsn, directory=DIRECTORY):
    import psycopg

    expected, scripts = _records(directory)
    with psycopg.connect(dsn) as connection:
        connection.execute("SET LOCAL search_path TO public")
        # Serialize both ledger creation and application across deployment workers.
        connection.execute("SELECT pg_advisory_xact_lock(73421009)")
        ledger = connection.execute("SELECT to_regclass('public.school_schema_migrations')").fetchone()[0]
        if ledger is None:
            present = connection.execute(
                "SELECT COUNT(*) FROM pg_tables WHERE schemaname='public'"
            ).fetchone()[0]
            if present:
                raise RuntimeError("Refusing to adopt an existing untracked schema")
            _create_ledger(connection)
        applied = connection.execute(
            "SELECT version, filename, checksum FROM public.school_schema_migrations ORDER BY version"
        ).fetchall()
        if applied != expected[:len(applied)]:
            raise RuntimeError("Migration history or checksum mismatch; refusing schema changes")
        for record, script in zip(expected[len(applied):], scripts[len(applied):]):
            connection.execute(script)
            connection.execute(
                "INSERT INTO public.school_schema_migrations(version,filename,checksum) VALUES(%s,%s,%s)",
                record,
            )
    return len(expected) - len(applied)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adopt-existing", action="store_true", help="Verify and record the known 001+002 baseline without replaying it")
    args = parser.parse_args()
    action = adopt_existing if args.adopt_existing else migrate
    count = action(os.environ["SCHOOL_POSTGRES_ADMIN_DSN"])
    print(f"Recorded {count} PostgreSQL migrations")
