import importlib.util
from pathlib import Path


def test_audit_detects_sqlite_only_constructs(tmp_path):
    path=Path(__file__).resolve().parents[1]/"scripts"/"audit_sqlite_sql.py"
    spec=importlib.util.spec_from_file_location("audit_sqlite_sql",path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path/"sample.py").write_text("c.execute('PRAGMA foreign_keys=ON')\ncur.lastrowid\n")
    found=module.audit(tmp_path)
    assert {x["pattern"] for x in found}=={"sqlite_pragma","sqlite_lastrowid"}


def test_existing_app_has_known_migration_work():
    path=Path(__file__).resolve().parents[1]/"scripts"/"audit_sqlite_sql.py"
    spec=importlib.util.spec_from_file_location("audit_sqlite_sql",path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert not any(f["pattern"]=="sqlite_lastrowid" for f in module.audit())
