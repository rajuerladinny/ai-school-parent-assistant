"""Versioned school policies with explicit approval and effective dates.

Dates are ISO local calendar dates (school timezone), compared against today's date.
Only approved, effective versions are indexed. Historical versions are retained.
"""
import sqlite3
from datetime import date, datetime, timezone
from fastapi import APIRouter, Header, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field
from . import conflicts, database_config

router = APIRouter(prefix="/api/policies", tags=["policies"])
_db = None
_auth = None
_extract = None
_reindex = None
_max_upload = 5 * 1024 * 1024

def configure(db, auth, extract, reindex):
    global _db, _auth, _extract, _reindex
    _db, _auth, _extract, _reindex = db, auth, extract, reindex

def setup(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS policy_versions (
        id INTEGER PRIMARY KEY, policy_key TEXT NOT NULL, version INTEGER NOT NULL,
        title TEXT NOT NULL, filename TEXT NOT NULL, content TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','approved','rejected')),
        effective_date TEXT NOT NULL, created_at TEXT NOT NULL,
        reviewed_at TEXT, UNIQUE(policy_key, version))""")
    cols={r[1] for r in connection.execute("PRAGMA table_info(policy_versions)")}
    if "school_id" not in cols:
        connection.execute("ALTER TABLE policy_versions ADD COLUMN school_id INTEGER NOT NULL DEFAULT 1 REFERENCES schools(id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_policy_versions_school ON policy_versions(school_id,policy_key,status,effective_date)")

def current_versions(connection, as_of=None, school_id=1):
    as_of = as_of or date.today().isoformat()
    # A newer approved version supersedes an older one only once effective.
    return connection.execute("""SELECT p.* FROM policy_versions p WHERE p.school_id=? AND p.status='approved'
        AND p.effective_date<=? AND p.version=(
            SELECT MAX(q.version) FROM policy_versions q
            WHERE q.school_id=p.school_id AND q.policy_key=p.policy_key AND q.status='approved' AND q.effective_date<=?
        ) ORDER BY p.policy_key""", (school_id, as_of, as_of)).fetchall()

def active_records(connection, as_of=None, school_id=1):
    return [{"id":f"policy-{p['id']}", "topic":p["title"],
             "source":f"{p['title']} v{p['version']} ({p['filename']})",
             "text":p["content"]} for p in current_versions(connection, as_of, school_id)]

def _authorized(key):
    _auth(key)

def _validate_date(value):
    try: return date.fromisoformat(value).isoformat()
    except (ValueError, TypeError): raise HTTPException(422, "effective_date must be YYYY-MM-DD")


def next_version(connection, policy_key, school_id=1):
    """Lock allocation until the caller's enclosing insert transaction ends.

    A school row exists before its first policy, so PostgreSQL can serialize
    even first uploads. Both upload APIs must use this same lock protocol.
    """
    if database_config.backend() == "sqlite":
        connection.execute("BEGIN IMMEDIATE")
        lock = ""
    else:
        lock = " FOR UPDATE"
    school = connection.execute(
        "SELECT id FROM schools WHERE id=? AND active=TRUE" + lock, (school_id,)
    ).fetchone()
    if not school:
        raise HTTPException(404, "Active school not found")
    return connection.execute(
        "SELECT COALESCE(MAX(version),0)+1 FROM policy_versions WHERE policy_key=? AND school_id=?",
        (policy_key, school_id)).fetchone()[0]


@router.get("")
def list_policies(x_admin_key: str | None = Header(None)):
    _authorized(x_admin_key)
    with _db() as c:
        return [dict(x) for x in c.execute("SELECT id,policy_key,version,title,filename,status,effective_date,created_at,reviewed_at FROM policy_versions WHERE school_id=1 ORDER BY policy_key,version DESC")]

@router.get("/active")
def active_policies():
    with _db() as c:
        return [{"policy_key":x["policy_key"],"version":x["version"],
                 "title":x["title"],"effective_date":x["effective_date"]}
                for x in current_versions(c)]

@router.post("", status_code=201)
async def upload_policy(policy_key: str = Form(...), title: str = Form(...),
                        effective_date: str = Form(...), file: UploadFile = File(...),
                        x_admin_key: str | None = Header(None)):
    _authorized(x_admin_key)
    policy_key = policy_key.strip().lower()
    if not (2 <= len(policy_key) <= 80) or not all(ch.isalnum() or ch in "-_" for ch in policy_key):
        raise HTTPException(422, "policy_key must be 2-80 letters, digits, hyphens or underscores")
    title = title.strip()
    if not (2 <= len(title) <= 150): raise HTTPException(422, "title must be 2-150 characters")
    effective_date = _validate_date(effective_date)
    filename = (file.filename or "").replace("\\", "/").split("/")[-1]
    if not filename or len(filename) > 180: raise HTTPException(400, "Invalid filename")
    data = await file.read(_max_upload + 1)
    if len(data) > _max_upload: raise HTTPException(413, "Maximum upload size is 5 MB")
    content = _extract(filename, data).strip()
    if not (30 <= len(content) <= 2_000_000):
        raise HTTPException(422, "Document must contain 30 to 2,000,000 characters")
    with _db() as c:
        version = next_version(c, policy_key)
        cur = c.execute("""INSERT INTO policy_versions
            (policy_key,version,title,filename,content,effective_date,created_at,school_id)
            VALUES (?,?,?,?,?,?,?,?) RETURNING id""",
            (policy_key,version,title,filename,content,effective_date,
             datetime.now(timezone.utc).isoformat(),1))
        return {"id":cur.fetchone()["id"], "policy_key":policy_key, "version":version,
                "status":"draft", "note":"Not visible to parents until approved and effective."}

class Decision(BaseModel):
    approve: bool

@router.post("/{policy_id}/review")
def review_policy(policy_id: int, decision: Decision, x_admin_key: str | None = Header(None)):
    _authorized(x_admin_key)
    with _db() as c:
        row = c.execute("SELECT status FROM policy_versions WHERE id=? AND school_id=1", (policy_id,)).fetchone()
        if not row: raise HTTPException(404, "Policy version not found")
        if row["status"] != "draft": raise HTTPException(409, "Only draft versions can be reviewed")
        if decision.approve:
            unresolved = conflicts.pending(c, policy_id)
            if unresolved:
                # Persist discovered overlaps even though approval is rejected.
                c.commit()
                raise HTTPException(409, f"{unresolved} unresolved legacy knowledge overlap(s); deactivate outdated items before approval")
        status = "approved" if decision.approve else "rejected"
        c.execute("UPDATE policy_versions SET status=?,reviewed_at=? WHERE id=? AND school_id=1",
                  (status,datetime.now(timezone.utc).isoformat(),policy_id))
    updated = _reindex()
    return {"id":policy_id, "status":status, "vector_index_updated":updated}
