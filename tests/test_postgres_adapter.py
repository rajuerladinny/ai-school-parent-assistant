import pytest
from app.postgres_adapter import placeholders,ConnectionAdapter


def test_sqlite_placeholders_only_outside_quotes():
    assert placeholders("SELECT '?' AS literal, x FROM t WHERE id=? AND note='it''s ?'")==(
        "SELECT '?' AS literal, x FROM t WHERE id=%s AND note='it''s ?'")
    assert placeholders('SELECT "?" FROM t WHERE a=?')=='SELECT "?" FROM t WHERE a=%s'


def test_sqlite_specific_sql_is_rejected():
    class Dummy:
        def execute(self,*args):raise AssertionError("Should not execute")
    adapter=ConnectionAdapter(Dummy())
    with pytest.raises(NotImplementedError):adapter.execute("PRAGMA foreign_keys=ON")
    with pytest.raises(NotImplementedError):adapter.execute("INSERT OR IGNORE INTO schools(id) VALUES(?)",(1,))


def test_adapter_executes_postgres_placeholders():
    class FakeCursor:
        rowcount=1
        def fetchone(self):return {"id":2}
    class FakeConnection:
        def execute(self,sql,params):
            assert sql=="SELECT * FROM schools WHERE id=%s"
            assert params==(2,)
            return FakeCursor()
    assert ConnectionAdapter(FakeConnection()).execute("SELECT * FROM schools WHERE id=?",(2,)).fetchone()=={"id":2}
