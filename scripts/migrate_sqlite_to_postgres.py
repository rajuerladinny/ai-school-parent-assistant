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
    "parent_notification_reads":("parent_id","policy_id","read_at"),
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
                        counts[table]=0
                        continue
                    available={r[1] for r in src.execute(f"PRAGMA table_info({table})")}
                    selected=[col for col in columns if col in available]
                    if "id" in columns and "id" not in selected:
                        raise ValueError(f"{table}: missing ID column")
                    rows=src.execute(f"SELECT {','.join(selected)} FROM {table}").fetchall()
                    counts[table]=len(rows)
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    if cur.fetchone()[0]:
                        raise ValueError(f"Target table {table} must be empty")
                    if rows:
                        placeholders=",".join(["%s"]*len(selected))
                        statement=f"INSERT INTO {table} ({','.join(selected)}) VALUES ({placeholders})"
                        cur.executemany(statement,[tuple(row) for row in rows])
                        cur.execute(f"SELECT COUNT(*) FROM {table}")
                        if cur.fetchone()[0]!=len(rows):
                            raise ValueError(f"Count mismatch in {table}")
                    if "id" in selected:
                        cur.execute(f"SELECT setval(pg_get_serial_sequence('{table}','id'), COALESCE((SELECT MAX(id) FROM {table}),1), (SELECT COUNT(*)>0 FROM {table}))")
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
