"""Portable idempotent inserts must not duplicate records."""
import sqlite3


def test_sqlite_on_conflict_do_nothing():
    with sqlite3.connect(":memory:") as c:
        c.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, name TEXT UNIQUE)")
        statement="INSERT INTO sample(id,name) VALUES(?,?) ON CONFLICT DO NOTHING"
        c.execute(statement,(1,"demo"))
        c.execute(statement,(1,"demo"))
        assert c.execute("SELECT COUNT(*) FROM sample").fetchone()[0]==1


def test_app_does_not_use_insert_or_ignore():
    from pathlib import Path
    app=Path(__file__).resolve().parents[1]/"app"
    for path in app.glob("*.py"):
        if path.name in ("postgres_adapter.py","database_config.py"):
            continue
        assert "INSERT OR IGNORE INTO" not in path.read_text(),path.name
