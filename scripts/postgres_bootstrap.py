"""Explicit PostgreSQL schema bootstrap and validation.

Run against a fresh isolated database. Never automatically initializes or
migrates a database during API startup.
"""
import argparse
from pathlib import Path

SCHEMA=Path(__file__).resolve().parents[1]/"migrations"/"postgresql"/"001_initial.sql"
REQUIRED=("schools","parent_accounts","parent_sessions","knowledge","documents",
          "policy_versions","escalations","escalation_events","parent_notification_reads",
          "knowledge_conflicts")


def validate(dsn):
    import psycopg
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname=current_schema()")
            present={r[0] for r in cursor.fetchall()}
            missing=set(REQUIRED)-present
            if missing:
                raise RuntimeError("PostgreSQL schema incomplete: "+", ".join(sorted(missing)))
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='policy_versions'")
            columns={r[0] for r in cursor.fetchall()}
            if "school_id" not in columns:
                raise RuntimeError("Tenant-aware policy schema is required")
    return True


def initialize_empty(dsn):
    import psycopg
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM pg_catalog.pg_tables WHERE schemaname=current_schema()")
            if cursor.fetchone()[0]:
                raise RuntimeError("Refusing to initialize a non-empty PostgreSQL schema")
            cursor.execute(SCHEMA.read_text())
    return validate(dsn)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn",required=True)
    parser.add_argument("--initialize-empty",action="store_true")
    args=parser.parse_args()
    if args.initialize_empty:initialize_empty(args.dsn)
    else:validate(args.dsn)
    print("PostgreSQL schema validated")
