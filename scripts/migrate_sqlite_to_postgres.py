"""Offline, transactional SQLite -> PostgreSQL data migration (non-destructive).

Run after applying migrations/postgresql/001_initial.sql to an EMPTY target database.
Do not run concurrently with application writes. Source SQLite is never modified.
This utility does not switch the application's runtime database adapter.
"""
import argparse
import sqlite3
from pathlib import Path

TABLES={
    "schools":("id","slug","name","active"),
    "parent_accounts":("id","school_id","username","display_name","salt","password_hash","enabled","created_at"),
    "knowledge":("id","school_id","topic","answer","source","active"),
    "documents":("id","school_id","filename","title","content","uploaded_at","active"),
    "policy_versions":("id","school_id","policy_key","version","title","filename","content","status","effective_date","created_at","reviewed_at"),
    "staff_accounts":("id","school_id","username","display_name","salt","password_hash","role","enabled","created_at"),
    "escalations":("id","school_id","parent_id","question","status","assigned_to","resolution","created_at","updated_at","resolved_at"),
    "escalation_events":("id","escalation_id","action","detail","created_at"),
    "knowledge_conflicts":("id","policy_id","legacy_type","legacy_id","status","created_at","resolved_at"),
    "parent_notification_reads":("parent_id","policy_id","read_at"),
    "parent_sessions":("token_hash","parent_id","expires_at"),
    "staff_sessions":("token_hash","staff_id","expires_at"),
}


def migrate(source_path, target_dsn, *, dry_run=True):
    import psycopg
    path=Path(source_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    src=sqlite3.connect(f"file:{path.resolve()}?mode=ro",uri=True)
    src.row_factory=sqlite3.Row
    try:
        with psycopg.connect(target_dsn) as dst:
            with dst.cursor() as cur:
                counts={}
                for table,columns in TABLES.items():
                    exists=src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
                    if not exists:
                        raise ValueError(f"Source table {table} is missing; migration requires a fully initialized SQLite schema")
                    available={r[1] for r in src.execute(f"PRAGMA table_info({table})")}
                    missing=set(columns)-available
                    if missing:
                        raise ValueError(f"{table}: missing required columns: {sorted(missing)}")
                    selected=list(columns)
                    rows=src.execute(f"SELECT {','.join(selected)} FROM {table}").fetchall()
                    counts[table]=len(rows)
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    if cur.fetchone()[0]:
                        raise ValueError(f"Target table {table} must be empty")
                    if rows:
                        # Foreign keys are loaded in dependency order: accounts and policies
                        # precede sessions and notification receipts.
                        # SQLite stores booleans as 0/1 and timestamps as ISO strings.
                        # psycopg requires Python booleans for PostgreSQL BOOLEAN columns.
                        boolean_columns={"schools":{"active"},"parent_accounts":{"enabled"},
                                         "staff_accounts":{"enabled"},"knowledge":{"active"},
                                         "documents":{"active"}}
                        values=[]
                        for row in rows:
                            values.append(tuple(bool(row[col]) if col in boolean_columns.get(table,set())
                                                else row[col] for col in selected))
                        placeholders=",".join(["%s"]*len(selected))
                        statement=f"INSERT INTO {table} ({','.join(selected)}) VALUES ({placeholders})"
                        cur.executemany(statement,values)
                        cur.execute(f"SELECT COUNT(*) FROM {table}")
                        if cur.fetchone()[0]!=len(rows):
                            raise ValueError(f"Count mismatch in {table}")
                    if "id" in selected:
                        cur.execute(f"SELECT setval(pg_get_serial_sequence('{table}','id'), COALESCE((SELECT MAX(id) FROM {table}),1), (SELECT COUNT(*)>0 FROM {table}))")
                # Verify relational integrity after all dependent tables are copied.
                for child,parent,foreign_key in (
                    ("parent_accounts","schools","school_id"),
                    ("staff_accounts","schools","school_id"),
                    ("parent_sessions","parent_accounts","parent_id"),
                    ("staff_sessions","staff_accounts","staff_id"),
                    ("escalations","schools","school_id"),
                    ("escalation_events","escalations","escalation_id"),
                    ("parent_notification_reads","parent_accounts","parent_id"),
                    ("parent_notification_reads","policy_versions","policy_id"),
                    ("knowledge_conflicts","policy_versions","policy_id"),
                ):
                    cur.execute(f"SELECT COUNT(*) FROM {child} c LEFT JOIN {parent} p ON c.{foreign_key}=p.id WHERE c.{foreign_key} IS NOT NULL AND p.id IS NULL")
                    if cur.fetchone()[0]:
                        raise ValueError(f"Broken foreign-key relationship: {child}.{foreign_key} -> {parent}")
                if dry_run:
                    dst.rollback()
                else:
                    dst.commit()
                return counts
    finally:
        src.close()


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite",required=True)
    parser.add_argument("--postgres-dsn",required=True)
    parser.add_argument("--apply",action="store_true",help="Commit after validation (default rolls back)")
    args=parser.parse_args()
    print(migrate(args.sqlite,args.postgres_dsn,dry_run=not args.apply))
