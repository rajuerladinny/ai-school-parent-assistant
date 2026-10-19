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

def test_cursor_adapter_supports_named_and_positional_fetchmany():
    from app.postgres_adapter import CursorAdapter
    class FakeCursor:
        def fetchmany(self,size):
            assert size==2
            return [{"id":7,"name":"A"},{"id":8,"name":"B"}]
    rows=CursorAdapter(FakeCursor()).fetchmany(2)
    assert rows[0]["id"]==7
    assert rows[0][0]==7
    assert rows[1][1]=="B"


def test_placeholder_conversion_resumes_after_line_comment():
    sql="SELECT id FROM schools -- comment with ?\nWHERE id=?"
    assert placeholders(sql)=="SELECT id FROM schools -- comment with ?\nWHERE id=%s"


def test_placeholder_conversion_ignores_block_comments():
    sql="SELECT /* ignore ? */ id FROM schools WHERE id=?"
    assert placeholders(sql)=="SELECT /* ignore ? */ id FROM schools WHERE id=%s"


def test_executemany_returns_open_cursor():
    class FakeCursor:
        rowcount=2
        closed=False
        def executemany(self,sql,params):
            assert sql=="INSERT INTO sample(value) VALUES(%s)"
            assert params==[(1,),(2,)]
        def close(self):self.closed=True
    class FakeConnection:
        def __init__(self):self.cur=FakeCursor()
        def cursor(self):return self.cur
    connection=FakeConnection()
    result=ConnectionAdapter(connection).executemany("INSERT INTO sample(value) VALUES(?)",[(1,),(2,)])
    assert result.rowcount==2
    assert not connection.cur.closed


def test_executemany_closes_cursor_on_error():
    class FakeCursor:
        closed=False
        def executemany(self,sql,params):raise ValueError("database error")
        def close(self):self.closed=True
    class FakeConnection:
        def __init__(self):self.cur=FakeCursor()
        def cursor(self):return self.cur
    connection=FakeConnection()
    with pytest.raises(ValueError,match="database error"):
        ConnectionAdapter(connection).executemany("INSERT INTO sample(value) VALUES(?)",[(1,)])
    assert connection.cur.closed


def test_executemany_rejects_sqlite_only_statements_before_opening_cursor():
    class FakeConnection:
        def cursor(self):
            raise AssertionError("Unsupported SQL must be rejected before opening cursor")
    adapter=ConnectionAdapter(FakeConnection())
    with pytest.raises(NotImplementedError, match="SQLite-only SQL"):
        adapter.executemany("INSERT OR IGNORE INTO schools(id) VALUES(?)", [(1,)])
    with pytest.raises(NotImplementedError, match="SQLite-only SQL"):
        adapter.executemany("PRAGMA foreign_keys=ON", [])
