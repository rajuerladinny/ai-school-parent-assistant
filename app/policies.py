"""Versioned school policies with explicit approval and effective dates.

Dates are ISO local calendar dates (school timezone), compared against today's date.
Only approved, effective versions are indexed. Historical versions are retained.
"""
import sqlite3
from datetime import date, datetime, timezone
from fastapi import APIRouter, Header, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field
from . import conflicts

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
    connection.execute("CREATE INDEX IF NOT EXISTS idx_policy_versions ON policy_versions(policy_key,status,effective_date)")

def current_versions(connection, as_of=None):
    as_of = as_of or date.today().isoformat()
    # A newer approved version supersedes an older one only once effective.
    return connection.execute("""SELECT p.* FROM policy_versions p WHERE p.status='approved'
        AND p.effective_date<=? AND p.version=(
            SELECT MAX(q.version) FROM policy_versions q
            WHERE q.policy_key=p.policy_key AND q.status='approved' AND q.effective_date<=?
        ) ORDER BY p.policy_key""", (as_of, as_of)).fetchall()

def active_records(connection, as_of=None):
    return [{"id":f"policy-{p['id']}", "topic":p["title"],
             "source":f"{p['title']} v{p['version']} ({p['filename']})",
             "text":p["content"]} for p in current_versions(connection, as_of)]

def _authorized(key):
    _auth(key)

def _validate_date(value):
    try: return date.fromisoformat(value).isoformat()
    except (ValueError, TypeError): raise HTTPException(422, "effective_date must be YYYY-MM-DD")

@router.get("")
def list_policies(x_admin_key: str | None = Header(None)):
    _authorized(x_admin_key)
    with _db() as c:
        return [dict(x) for x in c.execute("SELECT id,policy_key,version,title,filename,status,effective_date,created_at,reviewed_at FROM policy_versions ORDER BY policy_key,version DESC")]

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
        # IMMEDIATE transaction prevents concurrent uploads getting the same version.
        c.execute("BEGIN IMMEDIATE")
        version = c.execute("SELECT COALESCE(MAX(version),0)+1 FROM policy_versions WHERE policy_key=?", (policy_key,)).fetchone()[0]
        cur = c.execute("""INSERT INTO policy_versions
            (policy_key,version,title,filename,content,effective_date,created_at)
            VALUES (?,?,?,?,?,?,?)""",
            (policy_key,version,title,filename,content,effective_date,
             datetime.now(timezone.utc).isoformat()))
        return {"id":cur.lastrowid, "policy_key":policy_key, "version":version,
                "status":"draft", "note":"Not visible to parents until approved and effective."}

class Decision(BaseModel):
    approve: bool

@router.post("/{policy_id}/review")
def review_policy(policy_id: int, decision: Decision, x_admin_key: str | None = Header(None)):
    _authorized(x_admin_key)
    with _db() as c:
        row = c.execute("SELECT status FROM policy_versions WHERE id=?", (policy_id,)).fetchone()
        if not row: raise HTTPException(404, "Policy version not found")
        if row["status"] != "draft": raise HTTPException(409, "Only draft versions can be reviewed")
        if decision.approve:
            unresolved = conflicts.pending(c, policy_id)
            if unresolved:
                # Persist discovered overlaps even though approval is rejected.
                c.commit()
                raise HTTPException(409, f"{unresolved} unresolved legacy knowledge overlap(s); deactivate outdated items before approval")
        status = "approved" if decision.approve else "rejected"
        c.execute("UPDATE policy_versions SET status=?,reviewed_at=? WHERE id=?",
                  (status,datetime.now(timezone.utc).isoformat(),policy_id))
    updated = _reindex()
    return {"id":policy_id, "status":status, "vector_index_updated":updated}
