"""School-scoped knowledge administration using authenticated school-admin sessions.

The legacy shared-key API remains demo-only. These endpoints never accept a
school_id supplied by the caller; the tenant comes from the bearer principal.
"""
from fastapi import APIRouter, Header, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field
from . import staff_auth, conflicts, policies, auth
import secrets
import sqlite3
import hashlib
from datetime import datetime, timezone
from pathlib import Path

router = APIRouter(prefix="/api/school-admin", tags=["school-admin"])
_db = _reindex = _extract = None

def configure(db, reindex, extract):
    global _db, _reindex, _extract
    _db, _reindex, _extract = db, reindex, extract

class KnowledgeItem(BaseModel):
    topic: str = Field(min_length=2, max_length=100)
    answer: str = Field(min_length=5, max_length=2000)
    source: str = Field(min_length=2, max_length=150)

@router.get("/knowledge")
def list_knowledge(authorization: str | None = Header(None)):
    with _db() as c:
        user = staff_auth.principal(c, authorization, roles=("school_admin",))
        return [dict(row) for row in c.execute(
            "SELECT * FROM knowledge WHERE school_id=? ORDER BY id",
            (user["school_id"],))]

@router.post("/knowledge", status_code=201)
def add_knowledge(item: KnowledgeItem, authorization: str | None = Header(None)):
    with _db() as c:
        user = staff_auth.principal(c, authorization, roles=("school_admin",))
        cur = c.execute(
            "INSERT INTO knowledge(topic,answer,source,school_id) VALUES(?,?,?,?) RETURNING id",
            (item.topic, item.answer, item.source, user["school_id"]))
        item_id = cur.fetchone()["id"]
    indexed = _reindex()
    return {"id": item_id, "vector_index_updated": indexed}

@router.delete("/knowledge/{item_id}")
def delete_knowledge(item_id: int, authorization: str | None = Header(None)):
    with _db() as c:
        user = staff_auth.principal(c, authorization, roles=("school_admin",))
        result = c.execute(
            "DELETE FROM knowledge WHERE id=? AND school_id=?",
            (item_id, user["school_id"]))
        if not result.rowcount:
            raise HTTPException(404, "Knowledge item not found")
    _reindex()
    return {"deleted": True}

@router.get("/documents")
def list_documents(authorization: str | None = Header(None)):
    with _db() as c:
        user = staff_auth.principal(c, authorization, roles=("school_admin",))
        return [dict(row) for row in c.execute(
            "SELECT id,filename,title,active,uploaded_at,length(content) AS characters "
            "FROM documents WHERE school_id=? ORDER BY id DESC",
            (user["school_id"],))]

@router.delete("/documents/{document_id}")
def delete_document(document_id: int, authorization: str | None = Header(None)):
    with _db() as c:
        user = staff_auth.principal(c, authorization, roles=("school_admin",))
        result = c.execute(
            "DELETE FROM documents WHERE id=? AND school_id=?",
            (document_id, user["school_id"]))
        if not result.rowcount:
            raise HTTPException(404, "Document not found")
    _reindex()
    return {"deleted": True}

@router.get("/escalations")
def list_escalations(authorization: str | None = Header(None)):
    with _db() as c:
        user = staff_auth.principal(c, authorization, roles=("school_admin",))
        return [dict(row) for row in c.execute(
            "SELECT * FROM escalations WHERE school_id=? ORDER BY id DESC",
            (user["school_id"],))]

@router.post("/documents", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form("School document"),
    authorization: str | None = Header(None),
):
    # Authorize before reading or parsing untrusted uploads.
    with _db() as c:
        user = staff_auth.principal(c, authorization, roles=("school_admin",))
        school_id = user["school_id"]
    filename = Path(file.filename or "").name
    if not filename or len(filename) > 180:
        raise HTTPException(400, "Invalid filename")
    data = await file.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "Maximum upload size is 5 MB")
    content = _extract(filename, data).strip()
    if len(content) < 30:
        raise HTTPException(400, "Document contains too little extractable text")
    if len(content) > 2_000_000:
        raise HTTPException(413, "Extracted document text is too large")
    clean_title = title.strip()[:150] or filename
    with _db() as c:
        # Revalidate the bearer session before persisting a tenant-owned record.
        principal = staff_auth.principal(c, authorization, roles=("school_admin",))
        if principal["school_id"] != school_id:
            raise HTTPException(403, "School authorization changed")
        cur = c.execute(
            "INSERT INTO documents(filename,title,content,uploaded_at,school_id) "
            "VALUES(?,?,?,?,?) RETURNING id",
            (filename, clean_title, content, datetime.now(timezone.utc).isoformat(), school_id))
        document_id = cur.fetchone()["id"]
    indexed = _reindex()
    return {"id": document_id, "filename": filename, "characters": len(content),
            "vector_index_updated": indexed}

@router.get("/policies")
def list_policies(authorization: str | None = Header(None)):
    with _db() as c:
        user = staff_auth.principal(c, authorization, roles=("school_admin",))
        return [dict(row) for row in c.execute(
            "SELECT id,policy_key,version,title,filename,status,effective_date,created_at,reviewed_at "
            "FROM policy_versions WHERE school_id=? ORDER BY policy_key,version DESC",
            (user["school_id"],))]

@router.post("/policies", status_code=201)
async def upload_policy(
    policy_key: str = Form(...), title: str = Form(...),
    effective_date: str = Form(...), file: UploadFile = File(...),
    authorization: str | None = Header(None),
):
    with _db() as c:
        school_id = staff_auth.principal(c, authorization, roles=("school_admin",))["school_id"]
    key = policy_key.strip().lower()
    if not (2 <= len(key) <= 80) or not all(ch.isalnum() or ch in "-_" for ch in key):
        raise HTTPException(422, "Invalid policy key")
    title = title.strip()
    if not (2 <= len(title) <= 150):
        raise HTTPException(422, "Invalid title")
    effective_date = policies._validate_date(effective_date)
    filename = (file.filename or "").replace("\\", "/").split("/")[-1]
    if not filename or len(filename) > 180:
        raise HTTPException(400, "Invalid filename")
    data = await file.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "Maximum upload size is 5 MB")
    content = _extract(filename, data).strip()
    if not 30 <= len(content) <= 2_000_000:
        raise HTTPException(422, "Document must contain 30 to 2,000,000 characters")
    with _db() as c:
        user = staff_auth.principal(c, authorization, roles=("school_admin",))
        if user["school_id"] != school_id:
            raise HTTPException(403, "School authorization changed")
        if __import__("app.database_config", fromlist=["backend"]).backend() == "sqlite":
            c.execute("BEGIN IMMEDIATE")
        version = c.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM policy_versions WHERE policy_key=? AND school_id=?",
            (key, school_id)).fetchone()[0]
        cur = c.execute(
            "INSERT INTO policy_versions(policy_key,version,title,filename,content,effective_date,created_at,school_id) "
            "VALUES(?,?,?,?,?,?,?,?) RETURNING id",
            (key,version,title,filename,content,effective_date,
             datetime.now(timezone.utc).isoformat(),school_id))
        policy_id = cur.fetchone()["id"]
    return {"id":policy_id,"policy_key":key,"version":version,"status":"draft"}

class PolicyDecision(BaseModel):
    approve: bool

@router.post("/policies/{policy_id}/review")
def review_policy(policy_id: int, decision: PolicyDecision,
                  authorization: str | None = Header(None)):
    with _db() as c:
        user = staff_auth.principal(c, authorization, roles=("school_admin",))
        school_id = user["school_id"]
        policy = c.execute(
            "SELECT status FROM policy_versions WHERE id=? AND school_id=?",
            (policy_id,school_id)).fetchone()
        if not policy:
            raise HTTPException(404, "Policy version not found")
        if policy["status"] != "draft":
            raise HTTPException(409, "Only draft versions can be reviewed")
        if decision.approve:
            unresolved = conflicts.pending(c,policy_id,school_id)
            if unresolved:
                c.commit()
                raise HTTPException(409, f"{unresolved} unresolved legacy knowledge overlap(s)")
        status = "approved" if decision.approve else "rejected"
        c.execute(
            "UPDATE policy_versions SET status=?,reviewed_at=? WHERE id=? AND school_id=?",
            (status,datetime.now(timezone.utc).isoformat(),policy_id,school_id))
    indexed = _reindex()
    return {"id":policy_id,"status":status,"vector_index_updated":indexed}

@router.post("/policies/{policy_id}/conflicts/scan")
def scan_policy_conflicts(policy_id: int, authorization: str | None = Header(None)):
    with _db() as c:
        school_id = staff_auth.principal(c, authorization, roles=("school_admin",))["school_id"]
        items = conflicts.scan(c, policy_id, school_id)
        return {"policy_id": policy_id, "conflicts": [dict(x) for x in items],
                "pending": sum(x["status"] == "open" for x in items)}

@router.post("/legacy/{kind}/{item_id}/deactivate")
def deactivate_legacy(kind: str, item_id: int,
                      authorization: str | None = Header(None)):
    if kind not in ("faq", "document"):
        raise HTTPException(422, "Invalid knowledge type")
    table = "knowledge" if kind == "faq" else "documents"
    with _db() as c:
        school_id = staff_auth.principal(c, authorization, roles=("school_admin",))["school_id"]
        result = c.execute(
            f"UPDATE {table} SET active=FALSE WHERE id=? AND school_id=? AND active=TRUE",
            (item_id,school_id))
        if not result.rowcount:
            raise HTTPException(404, "Active knowledge item not found")
        c.execute(
            "UPDATE knowledge_conflicts SET status='resolved',resolved_at=CURRENT_TIMESTAMP "
            "WHERE legacy_type=? AND legacy_id=? AND status='open' "
            "AND policy_id IN (SELECT id FROM policy_versions WHERE school_id=?)",
            (kind,item_id,school_id))
    indexed = _reindex()
    return {"deactivated":True,"vector_index_updated":indexed}

class NewParent(BaseModel):
    username: str = Field(min_length=3,max_length=80,pattern=r"^[a-zA-Z0-9_.-]+$")
    display_name: str = Field(min_length=2,max_length=80)
    password: str = Field(min_length=12,max_length=128)

@router.post("/parents", status_code=201)
def create_parent(item: NewParent, authorization: str | None = Header(None)):
    salt = secrets.token_hex(16)
    with _db() as c:
        school_id = staff_auth.principal(c, authorization, roles=("school_admin",))["school_id"]
        try:
            cur = c.execute(
                "INSERT INTO parent_accounts(username,display_name,salt,password_hash,school_id) "
                "VALUES(?,?,?,?,?) RETURNING id",
                (item.username.lower(),item.display_name.strip(),salt,
                 auth.digest(item.password,salt),school_id))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Username already exists")
        parent_id = cur.fetchone()["id"]
    return {"id":parent_id,"username":item.username.lower(),"role":"parent"}

@router.post("/parents/{parent_id}/disable")
def disable_parent(parent_id: int, authorization: str | None = Header(None)):
    with _db() as c:
        school_id = staff_auth.principal(c, authorization, roles=("school_admin",))["school_id"]
        result = c.execute(
            "UPDATE parent_accounts SET enabled=FALSE WHERE id=? AND school_id=? AND enabled=TRUE",
            (parent_id,school_id))
        if not result.rowcount:
            raise HTTPException(404, "Enabled parent not found")
        c.execute("DELETE FROM parent_sessions WHERE parent_id=?", (parent_id,))
    return {"disabled":True}

class NewStaff(BaseModel):
    username: str = Field(min_length=3,max_length=80,pattern=r"^[a-zA-Z0-9_.-]+$")
    display_name: str = Field(min_length=2,max_length=80)
    password: str = Field(min_length=12,max_length=128)
    role: str = Field(default="staff",pattern=r"^staff$")

@router.post("/staff", status_code=201)
def create_staff(item: NewStaff, authorization: str | None = Header(None)):
    # School administrators can invite staff, not grant school_admin privileges.
    salt = secrets.token_hex(16)
    with _db() as c:
        school_id = staff_auth.principal(c, authorization, roles=("school_admin",))["school_id"]
        try:
            cur = c.execute(
                "INSERT INTO staff_accounts(school_id,username,display_name,salt,password_hash,role) "
                "VALUES(?,?,?,?,?,?) RETURNING id",
                (school_id,item.username.lower(),item.display_name.strip(),salt,
                 auth.digest(item.password,salt),item.role))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Username already exists")
        staff_id = cur.fetchone()["id"]
    return {"id":staff_id,"school_id":school_id,"role":item.role}

@router.post("/staff/{staff_id}/disable")
def disable_staff(staff_id: int, authorization: str | None = Header(None)):
    with _db() as c:
        principal = staff_auth.principal(c, authorization, roles=("school_admin",))
        result = c.execute(
            "UPDATE staff_accounts SET enabled=FALSE "
            "WHERE id=? AND school_id=? AND role='staff' AND enabled=TRUE",
            (staff_id,principal["school_id"]))
        if not result.rowcount:
            raise HTTPException(404, "Enabled staff account not found")
        c.execute("DELETE FROM staff_sessions WHERE staff_id=?", (staff_id,))
    return {"disabled":True}
