"""School-scoped knowledge administration using authenticated school-admin sessions.

The legacy shared-key API remains demo-only. These endpoints never accept a
school_id supplied by the caller; the tenant comes from the bearer principal.
"""
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from . import staff_auth

router = APIRouter(prefix="/api/school-admin", tags=["school-admin"])
_db = _reindex = None

def configure(db, reindex):
    global _db, _reindex
    _db, _reindex = db, reindex

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
