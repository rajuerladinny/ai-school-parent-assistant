import pytest
from app import database_config


def test_production_sqlite_rejected(monkeypatch):
    monkeypatch.setenv("SCHOOL_ENV", "production")
    monkeypatch.setenv("SCHOOL_DATABASE_BACKEND", "sqlite")
    with pytest.raises(RuntimeError, match="SQLite is not approved"):
        database_config.validate_configuration()


def test_postgres_flag_cannot_bypass_incomplete_adapter(monkeypatch):
    monkeypatch.setenv("SCHOOL_ENV", "production")
    monkeypatch.setenv("SCHOOL_DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("SCHOOL_POSTGRES_DSN", "postgresql://user:password@localhost/school")
    monkeypatch.setenv("SCHOOL_POSTGRES_RUNTIME_READY", "1")
    with pytest.raises(RuntimeError, match="adapter integration is not complete"):
        database_config.validate_configuration()


@pytest.mark.parametrize("dsn", [
    "", "sqlite:///school.db", "postgresql:///school",
    "postgresql://localhost/", "https://localhost/school",
])
def test_invalid_postgres_dsn_rejected(monkeypatch, dsn):
    monkeypatch.setenv("SCHOOL_DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("SCHOOL_POSTGRES_DSN", dsn)
    monkeypatch.setenv("SCHOOL_POSTGRES_RUNTIME_READY", "1")
    with pytest.raises(RuntimeError, match="SCHOOL_POSTGRES_DSN"):
        database_config.validate_configuration()
