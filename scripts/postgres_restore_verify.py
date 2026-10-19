"""Verify a PostgreSQL logical backup can restore into a fresh isolated database.

This tool NEVER drops or creates databases. Supply an already-created empty
restore database and a separate source database. Uses pg_dump and pg_restore.
"""
import argparse
import os
import subprocess
import tempfile

def verify(source_dsn, restore_dsn):
    from scripts.postgres_bootstrap import validate
    import psycopg
    if source_dsn == restore_dsn:
        raise ValueError("Source and restore DSNs must differ")
    with psycopg.connect(source_dsn) as source, psycopg.connect(restore_dsn) as target:
        source_info=source.execute(
            "SELECT current_database(),inet_server_addr()::text,inet_server_port()").fetchone()
        target_info=target.execute(
            "SELECT current_database(),inet_server_addr()::text,inet_server_port()").fetchone()
        if source_info == target_info:
            raise ValueError("Source and restore connections resolve to the same database")
        existing=target.execute(
            "SELECT COUNT(*) FROM pg_catalog.pg_tables WHERE schemaname=current_schema()").fetchone()[0]
        if existing:
            raise ValueError("Restore database schema must be empty")
    # Reject an incomplete or weakened source before creating a backup.
    validate(source_dsn)
    with tempfile.TemporaryDirectory(prefix="school-pg-restore-") as directory:
        backup=os.path.join(directory,"backup.dump")
        subprocess.run(["pg_dump","--format=custom","--no-owner","--no-acl",
                        "--file",backup,"--dbname",source_dsn],check=True)
        subprocess.run(["pg_restore","--no-owner","--no-acl","--exit-on-error",
                        "--dbname",restore_dsn,backup],check=True)
    validate(restore_dsn)
    with psycopg.connect(source_dsn) as source, psycopg.connect(restore_dsn) as restored:
        tables=("schools","parent_accounts","parent_sessions","staff_accounts",
                "staff_sessions","knowledge","documents","policy_versions",
                "escalations","escalation_events","parent_notification_reads",
                "knowledge_conflicts")
        counts={}
        for table in tables:
            original=source.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            copied=restored.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if original != copied:
                raise RuntimeError(f"Restore row-count mismatch in {table}")
            counts[table]=copied
    return counts

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dsn",required=True)
    parser.add_argument("--restore-dsn",required=True)
    args=parser.parse_args()
    counts=verify(args.source_dsn,args.restore_dsn)
    print("Restore verified; row counts:",counts)
