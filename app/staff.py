"""Admin-managed escalation workflow for unanswered parent questions."""
from datetime import datetime,timezone
from fastapi import APIRouter,Header,HTTPException
from pydantic import BaseModel,Field
from . import staff_auth

router=APIRouter(prefix="/api/staff",tags=["staff-workflow"])
_db=_auth=None

def configure(db,auth):
    global _db,_auth
    _db,_auth=db,auth

def setup(c):
    cols={r[1] for r in c.execute("PRAGMA table_info(escalations)")}
    for name,definition in (
        ("assigned_to","TEXT"),("resolution","TEXT"),
        ("updated_at","TEXT"),("resolved_at","TEXT")):
        if name not in cols:c.execute(f"ALTER TABLE escalations ADD COLUMN {name} {definition}")
    c.execute("""CREATE TABLE IF NOT EXISTS escalation_events(
        id INTEGER PRIMARY KEY,escalation_id INTEGER NOT NULL,
        action TEXT NOT NULL, detail TEXT, created_at TEXT NOT NULL)""")

class Update(BaseModel):
    status:str=Field(pattern="^(open|assigned|resolved)$")
    assigned_to:str|None=Field(default=None,max_length=80)
    resolution:str|None=Field(default=None,max_length=2000)

def now():return datetime.now(timezone.utc).isoformat()

@router.get("/questions")
def questions(status:str|None=None,x_admin_key:str|None=Header(None)):
    _auth(x_admin_key)
    if status is not None and status not in ("open","assigned","resolved"):
        raise HTTPException(422,"Invalid status")
    with _db() as c:
        if status:
            rows=c.execute("SELECT * FROM escalations WHERE status=? AND school_id=1 ORDER BY id DESC",(status,))
        else:
            rows=c.execute("SELECT * FROM escalations WHERE school_id=1 ORDER BY id DESC")
        return [dict(x) for x in rows]

@router.patch("/questions/{question_id}")
def update(question_id:int,payload:Update,x_admin_key:str|None=Header(None)):
    _auth(x_admin_key)
    assignee=(payload.assigned_to or "").strip()
    resolution=(payload.resolution or "").strip()
    if payload.status=="assigned" and not assignee:
        raise HTTPException(422,"Assigned questions require a staff assignee")
    if payload.status=="resolved" and not resolution:
        raise HTTPException(422,"Resolved questions require a resolution")
    with _db() as c:
        current=c.execute("SELECT id,status FROM escalations WHERE id=? AND school_id=1",(question_id,)).fetchone()
        if not current:raise HTTPException(404,"Question not found")
        if current["status"]=="resolved" and payload.status!="resolved":
            raise HTTPException(409,"Resolved questions cannot be reopened in this MVP")
        c.execute("""UPDATE escalations SET status=?,assigned_to=?,resolution=?,
            updated_at=?,resolved_at=? WHERE id=? AND school_id=1""",
            (payload.status,assignee or None,resolution or None,now(),
             now() if payload.status=="resolved" else None,question_id))
        c.execute("""INSERT INTO escalation_events(escalation_id,action,detail,created_at)
            VALUES(?,?,?,?)""",(question_id,payload.status,
            assignee if payload.status=="assigned" else resolution,now()))
    return {"id":question_id,"status":payload.status}

@router.get("/questions/{question_id}/history")
def history(question_id:int,x_admin_key:str|None=Header(None)):
    _auth(x_admin_key)
    with _db() as c:
        if not c.execute("SELECT id FROM escalations WHERE id=? AND school_id=1",(question_id,)).fetchone():
            raise HTTPException(404,"Question not found")
        return [dict(x) for x in c.execute(
            "SELECT action,detail,created_at FROM escalation_events WHERE escalation_id=? ORDER BY id",
            (question_id,))]


@router.get("/mine/questions")
def my_school_questions(status:str|None=None,authorization:str|None=Header(None)):
    if status is not None and status not in ("open","assigned","resolved"):
        raise HTTPException(422,"Invalid status")
    with _db() as c:
        user=staff_auth.principal(c,authorization)
        if status:
            rows=c.execute("SELECT * FROM escalations WHERE school_id=? AND status=? ORDER BY id DESC",(user["school_id"],status))
        else:
            rows=c.execute("SELECT * FROM escalations WHERE school_id=? ORDER BY id DESC",(user["school_id"],))
        return [dict(r) for r in rows]

@router.patch("/mine/questions/{question_id}")
def update_my_school_question(question_id:int,payload:Update,authorization:str|None=Header(None)):
    with _db() as c:
        user=staff_auth.principal(c,authorization)
        existing=c.execute("SELECT id,status FROM escalations WHERE id=? AND school_id=?",
                           (question_id,user["school_id"])).fetchone()
        if not existing:raise HTTPException(404,"Question not found")
        if existing["status"]=="resolved" and payload.status!="resolved":
            raise HTTPException(409,"Resolved questions cannot be reopened")
        assignee=(payload.assigned_to or "").strip()
        resolution=(payload.resolution or "").strip()
        if payload.status=="assigned" and not assignee:raise HTTPException(422,"Assignee required")
        if payload.status=="resolved" and not resolution:raise HTTPException(422,"Resolution required")
        if user["role"]=="staff":
            if existing["status"]=="assigned":
                ownership=c.execute("SELECT assigned_to FROM escalations WHERE id=? AND school_id=?",
                                    (question_id,user["school_id"])).fetchone()
                if ownership["assigned_to"]!=user["username"]:
                    raise HTTPException(403,"Question is assigned to another staff member")
            if payload.status=="assigned" and assignee!=user["username"]:
                raise HTTPException(403,"Staff can only assign questions to themselves")
        if assignee and payload.status=="assigned":
            assignee_row=c.execute("SELECT id FROM staff_accounts WHERE username=? AND school_id=? AND enabled=TRUE",
                                   (assignee,user["school_id"])).fetchone()
            if not assignee_row:
                raise HTTPException(422,"Assignee must be an active staff account in this school")
        c.execute("""UPDATE escalations SET status=?,assigned_to=?,resolution=?,updated_at=?,resolved_at=?
            WHERE id=? AND school_id=?""",(payload.status,assignee or None,resolution or None,now(),
                now() if payload.status=="resolved" else None,question_id,user["school_id"]))
        c.execute("INSERT INTO escalation_events(escalation_id,action,detail,created_at) VALUES(?,?,?,?)",
                  (question_id,payload.status,assignee if payload.status=="assigned" else resolution,now()))
        return {"id":question_id,"status":payload.status}
