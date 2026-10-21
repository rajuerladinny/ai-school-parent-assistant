"""Validate PostgreSQL schema bootstrap against CI's ephemeral database."""
import importlib.util
from pathlib import Path
import pytest


def module():
    path=Path(__file__).resolve().parents[1]/"scripts"/"postgres_bootstrap.py"
    spec=importlib.util.spec_from_file_location("pgbootstrap",path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_schema_declares_all_required_tables():
    m=module()
    sql=m.SCHEMA.read_text()
    for table in m.REQUIRED:
        assert f"CREATE TABLE IF NOT EXISTS {table} " in sql or f"CREATE TABLE IF NOT EXISTS {table} (" in sql


def test_bootstrap_against_postgres(postgres_database):
    dsn=postgres_database
    m=module()
    assert m.validate(dsn)
    with pytest.raises(RuntimeError,match="non-empty"):
        m.initialize_empty(dsn)
