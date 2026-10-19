"""Fail-closed migration tests: missing data structures must not silently disappear."""
import sqlite3
import sys
import types
import pytest
from scripts.migrate_sqlite_to_postgres import migrate, TABLES

class FakeCursor:
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def execute(self,*args):return self
    def fetchone(self):return (0,)

class FakeConnection:
    def __init__(self):self.rolled_back=False
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def cursor(self):return FakeCursor()
    def rollback(self):self.rolled_back=True

def test_migration_refuses_missing_source_table(tmp_path,monkeypatch):
    source=tmp_path/"incomplete.db"
    sqlite3.connect(source).close()
    monkeypatch.setitem(sys.modules,"psycopg",types.SimpleNamespace(connect=lambda dsn:FakeConnection()))
    with pytest.raises(ValueError,match="Source table schools is missing"):
        migrate(source,"fake",dry_run=True)

def test_migration_refuses_missing_columns(tmp_path,monkeypatch):
    source=tmp_path/"incomplete-columns.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE schools(id INTEGER PRIMARY KEY)")
    monkeypatch.setitem(sys.modules,"psycopg",types.SimpleNamespace(connect=lambda dsn:FakeConnection()))
    with pytest.raises(ValueError,match="schools: missing required columns"):
        migrate(source,"fake",dry_run=True)

def test_migration_includes_auth_and_escalation_records():
    assert {"parent_sessions","staff_accounts","staff_sessions","escalations",
            "escalation_events","knowledge_conflicts"} <= set(TABLES)
