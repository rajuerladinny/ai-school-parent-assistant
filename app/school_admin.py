"""School-scoped knowledge administration using authenticated school-admin sessions.

The legacy shared-key API remains demo-only. These endpoints never accept a
school_id supplied by the caller; the tenant comes from the bearer principal.
"""
from fastapi import APIRouter, Header, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field
from . import staff_auth
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
