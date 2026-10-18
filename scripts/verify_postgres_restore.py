"""Verify a PostgreSQL logical backup by restoring into a disposable database.

Requires PostgreSQL client binaries, a running server and credentials. Never restores
into the source database. Run against an isolated test cluster, not production.
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path


def run(*args,env=None):
    subprocess.run(list(args),check=True,env=env)


def verify(source_dsn,restore_dsn):
    if not source_dsn:
        raise ValueError("Source database DSN is required")
    if source_dsn==restore_dsn:
        raise ValueError("Source and restore database DSNs must differ")
    if not restore_dsn:
        raise ValueError("Disposable restore database DSN is required")
    with tempfile.TemporaryDirectory(prefix="school-backup-") as tmp:
        archive=str(Path(tmp)/"school.dump")
        run("pg_dump","--format=custom","--no-owner","--no-acl","--file",archive,"--dbname",source_dsn)
        if Path(archive).stat().st_size==0:
            raise RuntimeError("Backup archive is empty")
        run("pg_restore","--exit-on-error","--single-transaction","--no-owner","--no-acl",
            "--dbname",restore_dsn,archive)
        import psycopg
        with psycopg.connect(source_dsn) as source,psycopg.connect(restore_dsn) as restored:
            from scripts.migrate_sqlite_to_postgres import TABLES
            for table in TABLES:
                with source.cursor() as s,restored.cursor() as d:
                    s.execute(f"SELECT COUNT(*) FROM {table}")
                    d.execute(f"SELECT COUNT(*) FROM {table}")
                    if s.fetchone()[0]!=d.fetchone()[0]:
                        raise RuntimeError(f"Restore count mismatch: {table}")
        return True


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dsn",required=True)
    parser.add_argument("--restore-dsn",required=True,
                        help="MUST point to a separate, empty disposable database")
    args=parser.parse_args()
    verify(args.source_dsn,args.restore_dsn)
    print("Backup and restore row-count verification passed")
