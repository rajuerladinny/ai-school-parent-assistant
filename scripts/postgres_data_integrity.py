"""Compare all application values and identity sequence state after a restore."""
from collections import Counter


def sequence_state(connection, table):
    from psycopg import sql
    schema, name = connection.execute(
        "SELECT n.nspname,c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE c.oid=pg_get_serial_sequence(%s,'id')::regclass", (table,)).fetchone()
    return connection.execute(sql.SQL("SELECT last_value,is_called FROM {}.{}").format(
        sql.Identifier(schema), sql.Identifier(name))).fetchone()


def verify_data(source, restored):
    from scripts.migrate_sqlite_to_postgres import TABLES
    counts = {}
    for table, columns in TABLES.items():
        query = f"SELECT {','.join(columns)} FROM {table}"
        original = source.execute(query).fetchall()
        copied = restored.execute(query).fetchall()
        if len(original) != len(copied):
            raise RuntimeError(f"Restore row-count mismatch in {table}")
        if Counter(original) != Counter(copied):
            raise RuntimeError(f"Restore data mismatch in {table}")
        if "id" in columns and sequence_state(source, table) != sequence_state(restored, table):
            raise RuntimeError(f"Restore sequence mismatch in {table}")
        counts[table] = len(copied)
    ledger = "public.school_schema_migrations"
    original_ledger = source.execute("SELECT to_regclass(%s)", (ledger,)).fetchone()[0]
    restored_ledger = restored.execute("SELECT to_regclass(%s)", (ledger,)).fetchone()[0]
    if bool(original_ledger) != bool(restored_ledger):
        raise RuntimeError("Restore migration-history presence mismatch")
    if original_ledger:
        query = "SELECT version,filename,checksum,applied_at FROM public.school_schema_migrations ORDER BY version"
        if source.execute(query).fetchall() != restored.execute(query).fetchall():
            raise RuntimeError("Restore migration-history data mismatch")
    return counts
