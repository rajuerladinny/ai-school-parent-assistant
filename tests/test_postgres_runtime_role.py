"""Real PostgreSQL permission boundary tests on disposable databases only."""
import uuid

import pytest


@pytest.fixture
def runtime_role(postgres_empty_database):
    import psycopg
    from psycopg import sql
    from scripts.postgres_runtime_role import provision
    from scripts.postgres_migrations import migrate

    postgres_database = postgres_empty_database
    migrate(postgres_database)
    role = "school_runtime_" + uuid.uuid4().hex
    provision(postgres_database, role)
    try:
        yield postgres_database, role
    finally:
        with psycopg.connect(postgres_database, autocommit=True) as owner:
            owner.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            owner.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_runtime_can_use_identity_sequence_and_schema_validation(runtime_role):
    import psycopg
    from psycopg.conninfo import make_conninfo
    from app.postgres_adapter import connect
    from scripts.postgres_bootstrap import validate

    dsn, role = runtime_role
    restricted = make_conninfo(dsn, options="-c role=" + role)
    assert validate(restricted)
    with connect(restricted) as connection:
        row = connection.execute(
            "INSERT INTO schools(slug,name) VALUES(?,?) RETURNING id",
            ("restricted", "Fictional school"),
        ).fetchone()
        connection.execute("UPDATE schools SET name=? WHERE id=?", ("Updated", row["id"]))
        assert connection.execute("SELECT name FROM schools WHERE id=?", (row["id"],)).fetchone()[0] == "Updated"
        connection.execute("DELETE FROM schools WHERE id=?", (row["id"],))
    with psycopg.connect(restricted) as connection:
        assert connection.execute("SELECT current_user").fetchone()[0] == role


@pytest.mark.parametrize("statement", [
    "CREATE TABLE public.runtime_ddl_probe (id INT)",
    "ALTER TABLE schools ADD COLUMN runtime_ddl_probe INT",
    "DROP TABLE schools CASCADE",
    "TRUNCATE schools CASCADE",
    "ALTER TABLE schools DISABLE TRIGGER ALL",
    "CREATE ROLE runtime_escalation_probe",
    "DELETE FROM school_schema_migrations",
])
def test_runtime_cannot_change_schema_or_privileges(runtime_role, statement):
    import psycopg
    from psycopg.conninfo import make_conninfo

    dsn, role = runtime_role
    with psycopg.connect(make_conninfo(dsn, options="-c role=" + role)) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(statement)


def test_provision_refuses_existing_roles_without_changing_them(runtime_role):
    from scripts.postgres_runtime_role import provision

    dsn, role = runtime_role
    with pytest.raises(RuntimeError, match="already exists"):
        provision(dsn, role)


def test_runtime_school_disable_still_revokes_sessions(runtime_role):
    import psycopg
    from psycopg.conninfo import make_conninfo

    dsn, role = runtime_role
    with psycopg.connect(make_conninfo(dsn, options="-c role=" + role)) as connection:
        school = connection.execute(
            "INSERT INTO schools(slug,name) VALUES('session-school','Fictional school') RETURNING id"
        ).fetchone()[0]
        parent = connection.execute("""INSERT INTO parent_accounts
            (school_id,username,display_name,salt,password_hash)
            VALUES(%s,'fictional-parent','Fictional parent','test-salt','test-hash') RETURNING id""",
            (school,)).fetchone()[0]
        connection.execute("""INSERT INTO parent_sessions(token_hash,parent_id,expires_at)
            VALUES('fictional-token',%s,NOW()+INTERVAL '1 hour')""", (parent,))
        connection.execute("UPDATE schools SET active=FALSE WHERE id=%s", (school,))
        assert connection.execute("SELECT COUNT(*) FROM parent_sessions").fetchone()[0] == 0


def test_public_schema_create_grant_is_rejected_atomically(postgres_database):
    import psycopg
    from scripts.postgres_runtime_role import provision

    role = "school_runtime_" + uuid.uuid4().hex
    with psycopg.connect(postgres_database) as connection:
        connection.execute("GRANT CREATE ON SCHEMA public TO PUBLIC")
    with pytest.raises(RuntimeError, match="PUBLIC schema CREATE"):
        provision(postgres_database, role)
    with psycopg.connect(postgres_database) as connection:
        assert connection.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone() is None
