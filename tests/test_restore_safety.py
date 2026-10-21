"""Backup script safety checks (no production database required)."""
import importlib.util
from pathlib import Path
import pytest


def load():
    path=Path(__file__).resolve().parents[1]/"scripts"/"verify_postgres_restore.py"
    spec=importlib.util.spec_from_file_location("restore_check",path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reject_same_database():
    with pytest.raises(ValueError,match="must differ"):
        load().verify("postgresql://localhost/school","postgresql://localhost/school")


def test_reject_missing_restore_database():
    with pytest.raises(ValueError,match="required"):
        load().verify("postgresql://localhost/school","")


@pytest.mark.parametrize("script", ["verify_postgres_restore.py", "postgres_restore_verify.py"])
def test_restore_cli_help_from_another_directory(script, tmp_path):
    import os
    import subprocess
    import sys
    path=Path(__file__).resolve().parents[1]/"scripts"/script
    env=os.environ.copy()
    env.pop("PYTHONPATH",None)
    result=subprocess.run([sys.executable,str(path),"--help"],cwd=tmp_path,
                          env=env,capture_output=True,text=True,timeout=10)
    assert result.returncode == 0, result.stderr
    assert "--restore-dsn" in result.stdout
