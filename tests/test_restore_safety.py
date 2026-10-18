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
