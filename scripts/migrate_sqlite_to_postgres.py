"""Offline, transactional SQLite -> PostgreSQL data migration (non-destructive).

Run after applying migrations/postgresql/001_initial.sql to an EMPTY target database.
Do not run concurrently with application writes. Source SQLite is never modified.
This utility does not switch the application's runtime database adapter.
"""
import argparse
import sqlite3
from collections import Counter
from datetime import date, datetime, timezone
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

BOOLEAN_COLUMNS = {"schools": {"active"}, "parent_accounts": {"enabled"},
                   "staff_accounts": {"enabled"}, "knowledge": {"active"}, "documents": {"active"}}
TIMESTAMP_COLUMNS = {"created_at", "uploaded_at", "reviewed_at", "updated_at", "resolved_at", "read_at", "expires_at"}


def converted_value(table, column, value):
    if column in BOOLEAN_COLUMNS.get(table, set()):
        if not isinstance(value, int) or value not in (0, 1):
            raise ValueError(f"Invalid boolean in {table}.{column}; expected 0 or 1")
        return bool(value)
    if value is None:
        return None
    if column in TIMESTAMP_COLUMNS:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError):
            raise ValueError(f"Invalid timestamp in {table}.{column}") from None
        # SQLite CURRENT_TIMESTAMP is UTC; do not interpret it in the target's timezone.
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    if column == "effective_date":
        try:
            return date.fromisoformat(value)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid date in {table}.{column}") from None
    return value


def reset_sequence(cursor, table):
    """ALTER SEQUENCE RESTART rolls back; setval survives a transaction rollback."""
    from psycopg import sql
    cursor.execute("SELECT n.nspname,c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                   "WHERE c.oid=pg_get_serial_sequence(%s,'id')::regclass", (table,))
    sequence = cursor.fetchone()
    if sequence is None:
        raise ValueError(f"Missing identity sequence for {table}")
    cursor.execute(f"SELECT COALESCE(MAX(id),0)+1 FROM {table}")
    next_id = max(1, cursor.fetchone()[0])
    cursor.execute(sql.SQL("ALTER SEQUENCE {}.{} RESTART WITH {}").format(
        sql.Identifier(sequence[0]), sql.Identifier(sequence[1]), sql.Literal(next_id)))


def migrate(source_path, target_dsn, *, dry_run=True):
    import psycopg
    path=Path(source_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    src=sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True)
    src.row_factory=sqlite3.Row
    try:
        src.execute("BEGIN")
        # Retired/custom records require an explicit archive or migration decision.
        extra_tables = {row[0] for row in src.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT GLOB 'sqlite_*'")} - set(TABLES)
        for table in sorted(extra_tables):
            quoted = '"' + table.replace('"', '""') + '"'
            if src.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]:
                raise ValueError(f"Unmigrated source table {table} contains records; archive or migrate explicitly")
        with psycopg.connect(target_dsn) as dst:
            with dst.cursor() as cur:
                cur.execute("LOCK TABLE " + ",".join(TABLES) + " IN ACCESS EXCLUSIVE MODE")
                counts={}
                for table,columns in TABLES.items():
                    exists=src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
                    if not exists:
                        raise ValueError(f"Source table {table} is missing; migration requires a fully initialized SQLite schema")
                    available={r[1] for r in src.execute(f"PRAGMA table_info({table})")}
                    missing=set(columns)-available
                    if missing:
                        raise ValueError(f"{table}: missing required columns: {sorted(missing)}")
                    unexpected=available-set(columns)
                    if unexpected:
                        raise ValueError(f"Unmigrated source columns in {table}: {sorted(unexpected)}")
                    selected=list(columns)
                    rows=src.execute(f"SELECT {','.join(selected)} FROM {table}").fetchall()
                    counts[table]=len(rows)
                    values=[tuple(converted_value(table,col,row[col]) for col in selected) for row in rows]
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    if cur.fetchone()[0]:
                        raise ValueError(f"Target table {table} must be empty")
                    if rows:
                        # Foreign keys are loaded in dependency order: accounts and policies
                        # precede sessions and notification receipts.
                        # SQLite stores booleans as 0/1 and timestamps as ISO strings.
                        # psycopg requires Python booleans for PostgreSQL BOOLEAN columns.
                        placeholders=",".join(["%s"]*len(selected))
                        statement=f"INSERT INTO {table} ({','.join(selected)}) VALUES ({placeholders})"
                        cur.executemany(statement,values)
                        cur.execute(f"SELECT COUNT(*) FROM {table}")
                        if cur.fetchone()[0]!=len(rows):
                            raise ValueError(f"Count mismatch in {table}")
                # Verify after all inserts, so later triggers cannot alter an
                # already-checked table without detection. Never log record values.
                for table,columns in TABLES.items():
                    query=f"SELECT {','.join(columns)} FROM {table}"
                    original=src.execute(query).fetchall()
                    expected=(tuple(converted_value(table,col,row[col]) for col in columns) for row in original)
                    cur.execute(query)
                    if Counter(expected) != Counter(cur.fetchall()):
                        raise ValueError(f"Data mismatch in {table}")
                # Verify relational integrity after all dependent tables are copied.
                for child,parent,foreign_key in (
                    ("parent_accounts","schools","school_id"),
                    ("staff_accounts","schools","school_id"),
                    ("knowledge","schools","school_id"),
                    ("documents","schools","school_id"),
                    ("policy_versions","schools","school_id"),
                    ("parent_sessions","parent_accounts","parent_id"),
                    ("staff_sessions","staff_accounts","staff_id"),
                    ("escalations","schools","school_id"),
                    ("escalations","parent_accounts","parent_id"),
                    ("escalation_events","escalations","escalation_id"),
                    ("parent_notification_reads","parent_accounts","parent_id"),
                    ("parent_notification_reads","policy_versions","policy_id"),
                    ("knowledge_conflicts","policy_versions","policy_id"),
                ):
                    cur.execute(f"SELECT COUNT(*) FROM {child} c LEFT JOIN {parent} p ON c.{foreign_key}=p.id WHERE c.{foreign_key} IS NOT NULL AND p.id IS NULL")
                    if cur.fetchone()[0]:
                        raise ValueError(f"Broken foreign-key relationship: {child}.{foreign_key} -> {parent}")
                cur.execute("SELECT COUNT(*) FROM escalations e JOIN parent_accounts a ON a.id=e.parent_id "
                            "WHERE e.school_id<>a.school_id")
                if cur.fetchone()[0]:
                    raise ValueError("Cross-school tenant relationship in escalations.parent_id")
                for table, columns in TABLES.items():
                    if "id" in columns:
                        reset_sequence(cur, table)
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
