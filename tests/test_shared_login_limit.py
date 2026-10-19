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
    monkeypatch.setenv("SCHOOL_RATE_LIMIT_REDIS_URL", "rediss://localhost:6379/0")
    monkeypatch.setenv("SCHOOL_RATE_LIMIT_KEY_SECRET", "short")
    with pytest.raises(HTTPException) as error:
        shared_login_limit.check("staff", "alice", "127.0.0.1")
    assert error.value.status_code == 503

def test_atomic_limits_across_clients(monkeypatch):
    import sys
    import types
    monkeypatch.setenv("SCHOOL_ENV", "production")
    monkeypatch.setenv("SCHOOL_RATE_LIMIT_REDIS_URL", "rediss://localhost:6379/0")
    monkeypatch.setenv("SCHOOL_RATE_LIMIT_KEY_SECRET", "s" * 40)
    counters = {}
    class FakeRedis:
        @classmethod
        def from_url(cls, *args, **kwargs):
            return cls()
        def eval(self, script, keys, key, window):
            counters[key] = counters.get(key, 0) + 1
            return [counters[key], int(window)]
    monkeypatch.setitem(sys.modules, "redis", types.SimpleNamespace(Redis=FakeRedis))
    for _ in range(5):
        assert shared_login_limit.check("parent", "Alice", "192.0.2.1")
    with pytest.raises(HTTPException) as error:
        shared_login_limit.check("parent", "alice", "192.0.2.2")
    assert error.value.status_code == 429
    assert int(error.value.headers["Retry-After"]) > 0
    # Source-IP protection also applies across distinct accounts.
    for i in range(29):
        assert shared_login_limit.check("staff", f"user{i}", "198.51.100.1")
    assert shared_login_limit.check("staff", "user29", "198.51.100.1")
    with pytest.raises(HTTPException) as error:
        shared_login_limit.check("staff", "user30", "198.51.100.1")
    assert error.value.status_code == 429

def test_plaintext_redis_refused_in_production(monkeypatch):
    monkeypatch.setenv("SCHOOL_ENV", "production")
    monkeypatch.setenv("SCHOOL_RATE_LIMIT_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SCHOOL_RATE_LIMIT_KEY_SECRET", "s" * 40)
    monkeypatch.delenv("SCHOOL_ALLOW_INSECURE_REDIS", raising=False)
    with pytest.raises(HTTPException) as error:
        shared_login_limit.check("parent", "alice", "127.0.0.1")
    assert error.value.status_code == 503

def test_redis_outage_fails_closed(monkeypatch):
    import sys
    import types
    monkeypatch.setenv("SCHOOL_ENV", "production")
    monkeypatch.setenv("SCHOOL_RATE_LIMIT_REDIS_URL", "rediss://localhost:6379/0")
    monkeypatch.setenv("SCHOOL_RATE_LIMIT_KEY_SECRET", "s" * 40)
    class BrokenRedis:
        @classmethod
        def from_url(cls, *args, **kwargs):
            return cls()
        def eval(self, *args):
            raise ConnectionError("redis unavailable")
    monkeypatch.setitem(sys.modules, "redis", types.SimpleNamespace(Redis=BrokenRedis))
    with pytest.raises(HTTPException) as error:
        shared_login_limit.check("parent", "alice", "192.0.2.1")
    assert error.value.status_code == 503
    assert "redis" not in str(error.value.detail).lower()
