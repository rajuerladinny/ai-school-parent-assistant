"""Production must remain fail-closed until shared authentication throttling exists."""
import os
import subprocess
import sys


def test_production_refuses_process_local_login_throttling():
    env=os.environ.copy()
    env.update({
        "SCHOOL_ENV":"production",
        "SCHOOL_ADMIN_KEY":"a"*40,
        "SCHOOL_ALLOWED_HOSTS":"school.example.test",
        "SCHOOL_ENFORCE_HTTPS":"1",
    })
    result=subprocess.run(
        [sys.executable,"-c","import app.main"],
        env=env,capture_output=True,text=True,timeout=20,
    )
    assert result.returncode!=0
    assert "shared Redis login limiter configuration" in result.stderr


def _run_production_import(**overrides):
    """Check startup configuration in a clean child process."""
    env = os.environ.copy()
    env.update({
        "SCHOOL_ENV": "production",
        "SCHOOL_ADMIN_KEY": "a" * 40,
        "SCHOOL_ALLOWED_HOSTS": "school.example.test",
        "SCHOOL_ENFORCE_HTTPS": "1",
        "SCHOOL_RATE_LIMIT_REDIS_URL": "rediss://localhost:6379/0",
        "SCHOOL_RATE_LIMIT_KEY_SECRET": "s" * 40,
    })
    env.update(overrides)
    return subprocess.run(
        [sys.executable, "-c", "import app.main"],
        env=env, capture_output=True, text=True, timeout=20,
    )


def test_production_rejects_wildcard_hosts():
    result = _run_production_import(SCHOOL_ALLOWED_HOSTS="*")
    assert result.returncode != 0
    assert "explicit SCHOOL_ALLOWED_HOSTS" in result.stderr


def test_production_rejects_missing_allowed_hosts():
    result = _run_production_import(SCHOOL_ALLOWED_HOSTS="")
    assert result.returncode != 0
    assert "explicit SCHOOL_ALLOWED_HOSTS" in result.stderr


def test_production_requires_https_enforcement():
    result = _run_production_import(SCHOOL_ENFORCE_HTTPS="0")
    assert result.returncode != 0
    assert "SCHOOL_ENFORCE_HTTPS=1" in result.stderr


def test_production_rejects_plaintext_redis_by_default():
    result = _run_production_import(
        SCHOOL_RATE_LIMIT_REDIS_URL="redis://localhost:6379/0",
        SCHOOL_ALLOW_INSECURE_REDIS="0",
    )
    assert result.returncode != 0
    assert "TLS Redis transport" in result.stderr
