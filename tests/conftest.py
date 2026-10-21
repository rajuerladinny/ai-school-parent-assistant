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
