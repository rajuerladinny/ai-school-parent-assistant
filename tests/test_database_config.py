import pytest
from app import database_config


def test_default_sqlite_allowed_for_demo(monkeypatch):
    monkeypatch.delenv("SCHOOL_ENV",raising=False)
    monkeypatch.delenv("SCHOOL_DATABASE_BACKEND",raising=False)
    assert database_config.validate_configuration()=="sqlite"


def test_postgres_cannot_be_activated_prematurely(monkeypatch):
    monkeypatch.setenv("SCHOOL_DATABASE_BACKEND","postgres")
    monkeypatch.setenv("SCHOOL_POSTGRES_DSN","postgresql://localhost/school")
    monkeypatch.setenv("SCHOOL_POSTGRES_RUNTIME_READY","1")
    with pytest.raises(RuntimeError,match="integration is not complete"):
        database_config.validate_configuration()


def test_sqlite_rejected_in_production(monkeypatch):
    monkeypatch.setenv("SCHOOL_DATABASE_BACKEND","sqlite")
    monkeypatch.setenv("SCHOOL_ENV","production")
    with pytest.raises(RuntimeError,match="not approved"):
        database_config.validate_configuration()
