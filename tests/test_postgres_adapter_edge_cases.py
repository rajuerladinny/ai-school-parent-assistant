import pytest
from app.postgres_adapter import placeholders, ConnectionAdapter


@pytest.mark.parametrize(("sql","expected"), [
    ("SELECT ? -- ?", "SELECT %s -- ?"),
    ("SELECT ? /* ? */ FROM t WHERE id=?", "SELECT %s /* ? */ FROM t WHERE id=%s"),
    ("SELECT '?' AS literal, ? AS value", "SELECT '?' AS literal, %s AS value"),
    ('SELECT "?" AS identifier, ? AS value', 'SELECT "?" AS identifier, %s AS value'),
    ("SELECT 'it''s ?' AS literal, ?", "SELECT 'it''s ?' AS literal, %s"),
])
def test_placeholder_current_conversion_contract(sql,expected):
    assert placeholders(sql)==expected


def test_sqlite_pragma_rejected_before_connection_execute():
    class FakeConnection:
        def execute(self,*args):
            raise AssertionError("Database must not receive PRAGMA")
    with pytest.raises(NotImplementedError):
        ConnectionAdapter(FakeConnection()).execute("  PRAGMA busy_timeout=1000")
