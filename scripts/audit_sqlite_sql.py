"""Static audit of SQLite-only SQL patterns before PostgreSQL runtime activation.

Run: python scripts/audit_sqlite_sql.py
Returns a nonzero exit code only if --strict is requested and findings remain.
"""
import argparse
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/"app"
PATTERNS={
    "sqlite_pragma":re.compile(r"\bPRAGMA\b",re.I),
    "sqlite_insert_ignore":re.compile(r"\bINSERT\s+OR\s+IGNORE\b",re.I),
    "sqlite_lastrowid":re.compile(r"\blastrowid\b",re.I),
    "sqlite_table_info":re.compile(r"\btable_info\s*\(",re.I),
    "sqlite_integer_pk":re.compile(r"\bINTEGER\s+PRIMARY\s+KEY\b",re.I),
    "sqlite_collate_nocase":re.compile(r"\bCOLLATE\s+NOCASE\b",re.I),
}


def audit(root=ROOT):
    findings=[]
    for path in sorted(root.glob("*.py")):
        if path.name in ("postgres_adapter.py","database_config.py"):
            continue
        for lineno,line in enumerate(path.read_text().splitlines(),1):
            for name,pattern in PATTERNS.items():
                if pattern.search(line):
                    findings.append({"file":path.name,"line":lineno,"pattern":name})
    return findings


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict",action="store_true")
    args=parser.parse_args()
    findings=audit()
    for finding in findings:
        print(f"{finding['file']}:{finding['line']}: {finding['pattern']}")
    print(f"{len(findings)} SQLite-specific occurrences remain")
    if args.strict and findings:
        raise SystemExit(1)
