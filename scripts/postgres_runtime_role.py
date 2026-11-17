"""Create a fresh, non-login runtime permission group using a database owner DSN.

Credentials and login membership are managed separately by the deployment owner.
This never grants schema creation, ownership, TRUNCATE or migration privileges.
"""
import argparse
import os

from scripts.postgres_bootstrap import REQUIRED, validate


def provision(dsn, role):
    import psycopg
    from psycopg import sql

    validate(dsn)
    with psycopg.connect(dsn) as connection:
        schema, database = connection.execute(
            "SELECT current_schema(), current_database()"
        ).fetchone()
        # A fresh group avoids silently preserving inherited/previous grants.
        if connection.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
            raise RuntimeError("Runtime permission group already exists; inspect its privileges explicitly")
        connection.execute(sql.SQL(
            "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
        ).format(sql.Identifier(role)))
        connection.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(database), sql.Identifier(role)))
        # PostgreSQL privileges are additive: PUBLIC CREATE would undermine this group.
        if connection.execute(
            "SELECT has_schema_privilege(%s, %s, 'CREATE')", (role, schema)
        ).fetchone()[0]:
            raise RuntimeError("Remove PUBLIC schema CREATE privileges before provisioning runtime access")
        connection.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
            sql.Identifier(schema), sql.Identifier(role)))
        for table in REQUIRED:
            connection.execute(sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {}.{} TO {}"
            ).format(sql.Identifier(schema), sql.Identifier(table), sql.Identifier(role)))
        # Only grant usage on sequences actually owned by application columns.
        sequences = connection.execute("""
            SELECT DISTINCT ns.nspname, seq.relname FROM pg_class seq
            JOIN pg_namespace ns ON ns.oid=seq.relnamespace
            JOIN pg_depend dep ON dep.objid=seq.oid AND dep.deptype IN ('a','i')
            JOIN pg_class tab ON tab.oid=dep.refobjid
            JOIN pg_namespace tn ON tn.oid=tab.relnamespace
            WHERE seq.relkind='S' AND tn.nspname=%s AND tab.relname=ANY(%s)
        """, (schema, list(REQUIRED))).fetchall()
        for namespace, sequence in sequences:
            connection.execute(sql.SQL("GRANT USAGE ON SEQUENCE {}.{} TO {}").format(
                sql.Identifier(namespace), sql.Identifier(sequence), sql.Identifier(role)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True)
    args = parser.parse_args()
    provision(os.environ["SCHOOL_POSTGRES_ADMIN_DSN"], args.role)
    print("Runtime permission group created; login credentials were not changed")
