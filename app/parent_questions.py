"""Authenticated parent question tracking and ownership isolation."""
from fastapi import APIRouter,Header
from . import auth as parent_auth

router=APIRouter(prefix="/api/parent/questions",tags=["parent-questions"])
_db=None

def configure(db):
    global _db
    _db=db

def setup(c):
    cols={r[1] for r in c.execute("PRAGMA table_info(escalations)")}
    if "parent_id" not in cols:
        c.execute("ALTER TABLE escalations ADD COLUMN parent_id INTEGER")
    c.execute("CREATE INDEX IF NOT EXISTS idx_escalations_parent ON escalations(parent_id)")

@router.get("")
def my_questions(authorization:str|None=Header(None)):
    with _db() as c:
        parent=parent_auth.parent(c,authorization)
        parent_auth.require_demo_school(parent)
        return [dict(r) for r in c.execute("""SELECT id,question,status,assigned_to,
            CASE WHEN status='resolved' THEN resolution ELSE NULL END AS resolution,
            created_at,updated_at,resolved_at
            FROM escalations WHERE parent_id=? ORDER BY id DESC""",(parent["id"],))]
