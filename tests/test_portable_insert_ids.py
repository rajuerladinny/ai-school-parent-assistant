import sqlite3
from pathlib import Path


def test_sqlite_returning_insert_id():
    c=sqlite3.connect(":memory:")
    c.row_factory=sqlite3.Row
    c.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY,name TEXT)")
    row=c.execute("INSERT INTO sample(name) VALUES(?) RETURNING id",("example",)).fetchone()
    assert row["id"]==1
    c.close()


def test_application_uses_no_lastrowid():
    root=Path(__file__).resolve().parents[1]/"app"
    for path in root.glob("*.py"):
        if path.name=="postgres_adapter.py":continue
        assert ".lastrowid" not in path.read_text(),path.name
