import pytest
from fastapi import HTTPException
from app import shared_login_limit


def test_development_does_not_require_redis(monkeypatch):
    monkeypatch.delenv("SCHOOL_ENV", raising=False)
    assert shared_login_limit.check("parent", "alice", "127.0.0.1") is False


def test_production_missing_redis_fails_closed(monkeypatch):
    monkeypatch.setenv("SCHOOL_ENV", "production")
    monkeypatch.delenv("SCHOOL_RATE_LIMIT_REDIS_URL", raising=False)
    with pytest.raises(HTTPException) as error:
        shared_login_limit.check("parent", "alice", "127.0.0.1")
    assert error.value.status_code == 503


def test_production_missing_secret_fails_closed(monkeypatch):
    monkeypatch.setenv("SCHOOL_ENV", "production")
    monkeypatch.setenv("SCHOOL_RATE_LIMIT_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SCHOOL_RATE_LIMIT_KEY_SECRET", "short")
    with pytest.raises(HTTPException) as error:
        shared_login_limit.check("staff", "alice", "127.0.0.1")
    assert error.value.status_code == 503
