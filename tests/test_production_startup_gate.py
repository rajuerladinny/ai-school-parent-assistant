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
    assert "shared login rate limiter is not implemented" in result.stderr
