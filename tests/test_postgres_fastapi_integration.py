"""Actual FastAPI HTTP requests backed by a disposable PostgreSQL database.

The test temporarily patches the startup readiness gate, never changes the
production configuration gate. This isolates SQL/API compatibility from release approval.
"""
import os
import uuid
from urllib.parse import urlsplit,urlunsplit
import pytest


def test_fastapi_postgres_health_and_school_scoped_read(monkeypatch):
    dsn=os.getenv("TEST_POSTGRES_URL")
    if not dsn:pytest.skip("Requires TEST_POSTGRES_URL")
    import psycopg
    from fastapi.testclient import TestClient
    from app import main,database_config
    from scripts.postgres_bootstrap import initialize_empty
    parts=urlsplit(dsn)
    name="school_api_"+uuid.uuid4().hex[:12]
    admin=urlunsplit((parts.scheme,parts.netloc,"/postgres",parts.query,parts.fragment))
    target=urlunsplit((parts.scheme,parts.netloc,"/"+name,parts.query,parts.fragment))
    with psycopg.connect(admin,autocommit=True) as root:
        root.execute(f'CREATE DATABASE "{name}"')
    try:
        initialize_empty(target)
        with psycopg.connect(target) as c:
            c.execute("INSERT INTO schools(id,slug,name) VALUES(1,'demo','Demo School')")
            c.execute("INSERT INTO knowledge(school_id,topic,answer,source) VALUES(1,'Timings','9 AM','Handbook')")
        monkeypatch.setenv("SCHOOL_DATABASE_BACKEND","postgres")
        monkeypatch.setenv("SCHOOL_POSTGRES_DSN",target)
        monkeypatch.setenv("SCHOOL_ADMIN_KEY","test-key-for-integration")
        monkeypatch.setattr(database_config,"validate_configuration",lambda:"postgres")
        monkeypatch.setattr(main,"rebuild_index",lambda:False)
        with TestClient(main.app) as client:
            health=client.get("/api/health")
            assert health.status_code==200
            response=client.get("/api/knowledge",headers={"x-admin-key":"test-key-for-integration"})
            assert response.status_code==200,response.text
            assert len(response.json())==1
            assert response.json()[0]["topic"]=="Timings"
    finally:
        with psycopg.connect(admin,autocommit=True) as root:
            root.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
