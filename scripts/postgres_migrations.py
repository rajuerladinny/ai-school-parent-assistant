"""Apply ordered PostgreSQL migrations atomically with a checksum ledger.

Fresh databases only for the initial adoption. Existing untracked schemas are
rejected and must be migrated through an independently reviewed adoption plan.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re

DIRECTORY = Path(__file__).resolve().parents[1] / "migrations" / "postgresql"


def migrate(dsn, directory=DIRECTORY):
    import psycopg

    files = sorted(directory.glob("[0-9][0-9][0-9]_*.sql"))
    versions = [path.name[:3] for path in files]
    if not files or len(set(versions)) != len(versions):
        raise RuntimeError("Migration versions must be present and unique")
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
            connection.execute("""CREATE TABLE public.school_schema_migrations (
                version TEXT PRIMARY KEY, filename TEXT NOT NULL, checksum TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
        applied = connection.execute(
            "SELECT version, filename, checksum FROM public.school_schema_migrations ORDER BY version"
        ).fetchall()
        expected = []
        scripts = []
        for path in files:
            content = path.read_text(encoding="utf-8").replace("\r\n", "\n")
            expected.append((path.name[:3], path.name, hashlib.sha256(content.encode()).hexdigest()))
            # Legacy scripts have their own transaction wrappers. The runner owns
            # the enclosing transaction so DDL and ledger updates commit together.
            scripts.append(re.sub(r"^(BEGIN|COMMIT);\s*$", "", content, flags=re.MULTILINE))
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
    argparse.ArgumentParser(description=__doc__).parse_args()
    count = migrate(os.environ["SCHOOL_POSTGRES_ADMIN_DSN"])
    print(f"Applied {count} PostgreSQL migrations")
