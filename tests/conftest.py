"""Isolated PostgreSQL fixtures; TEST_POSTGRES_URL supplies server access only."""
import os
import uuid
from urllib.parse import urlsplit, urlunsplit

import pytest


@pytest.fixture
def postgres_database():
    """Initialize a fresh database for one test and remove it on every exit."""
    url = os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Requires TEST_POSTGRES_URL")
    import psycopg
    from psycopg import sql
    from scripts.postgres_bootstrap import initialize_empty

    parts = urlsplit(url)
    name = "school_test_" + uuid.uuid4().hex
    admin = urlunsplit(parts._replace(path="/postgres"))
    target = urlunsplit(parts._replace(path="/" + name))
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        initialize_empty(target)
        yield target
    finally:
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.fixture
def policy_index_database(tmp_path, monkeypatch):
    """Fictional policies across active and disabled schools, without loading a model."""
    from datetime import date, timedelta, datetime, timezone
    from app import main

    monkeypatch.setenv("SCHOOL_ENV", "test")
    monkeypatch.setenv("SCHOOL_DATABASE_BACKEND", "sqlite")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.setattr(main, "DB", str(tmp_path / "policy-index.db"))
    monkeypatch.setattr(main, "_last_policy_index_date", None)
    main.setup()
    today = date.today().isoformat()
    future = (date.today() + timedelta(days=10)).isoformat()
    with main.db() as connection:
        connection.execute("DELETE FROM knowledge")
        connection.execute("INSERT INTO schools(id,slug,name,active) VALUES(2,'two','School Two',1),(3,'three','School Three',0)")
        for row in (
            (101,1,"fees-one",1,"one.txt","School ONE fee policy is approved and effective.","approved",today),
            (102,1,"fees-one",2,"future.txt","FUTURE fee policy must not be retrieved yet.","approved",future),
            (201,2,"fees-two",1,"two.txt","School TWO fee policy is approved and effective.","approved",today),
            (202,2,"fees-two",2,"draft.txt","DRAFT fee policy must not be retrieved.","draft",today),
            (203,2,"fees-two",3,"rejected.txt","REJECTED fee policy must not be retrieved.","rejected",today),
            (301,3,"fees-three",1,"three.txt","School THREE fee policy must not be retrieved.","approved",today),
        ):
            connection.execute(
                "INSERT INTO policy_versions(id,school_id,policy_key,version,filename,content,status,effective_date,title,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,'Fee policy',?)", (*row, datetime.now(timezone.utc).isoformat()))
        for school_id in (2,3):
            connection.execute("INSERT INTO knowledge(school_id,topic,answer,source) VALUES(?,'Bus','Fictional bus route','Transport')", (school_id,))
            connection.execute("INSERT INTO documents(school_id,filename,title,content,uploaded_at) VALUES(?,'library.txt','Library','Fictional library book returns',?)",
                               (school_id, datetime.now(timezone.utc).isoformat()))
    return main
