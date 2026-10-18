"""Opt-in in-app policy update inbox. No external email/SMS delivery."""
import secrets
from datetime import date
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, Field

router=APIRouter(prefix="/api/notifications",tags=["notifications"])
_db=_auth=None

def configure(db,auth):
    global _db,_auth
    _db,_auth=db,auth

def setup(c):
    c.execute("""CREATE TABLE IF NOT EXISTS notification_subscribers(
      id INTEGER PRIMARY KEY, token TEXT NOT NULL UNIQUE,
      label TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS notification_reads(
      subscriber_id INTEGER NOT NULL, policy_id INTEGER NOT NULL,
      read_at TEXT DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY(subscriber_id,policy_id))""")

class Subscribe(BaseModel):
    label:str=Field(min_length=2,max_length=80)

@router.post("/subscribe",status_code=201)
def subscribe(payload:Subscribe):
    # Demo: anonymous opaque token, returned once. Do not collect student or contact details.
    token=secrets.token_urlsafe(32)
    with _db() as c:
        c.execute("INSERT INTO notification_subscribers(token,label) VALUES(?,?)",
                  (token,payload.label.strip()))
    return {"token":token,"message":"Save this private token to read your notification inbox."}

def subscriber(c,token):
    if not token: raise HTTPException(401,"Notification token required")
    row=c.execute("SELECT id FROM notification_subscribers WHERE token=?",(token,)).fetchone()
    if not row: raise HTTPException(401,"Invalid notification token")
    return row["id"]

@router.get("")
def inbox(x_notification_token:str|None=Header(None)):
    with _db() as c:
        sid=subscriber(c,x_notification_token)
        # Only approved versions that are currently effective; future policies remain hidden.
        return [dict(r) for r in c.execute("""SELECT p.id AS policy_id,p.policy_key,p.title,
             p.version,p.effective_date,
             CASE WHEN r.policy_id IS NULL THEN 0 ELSE 1 END AS is_read
             FROM policy_versions p
             LEFT JOIN notification_reads r ON r.policy_id=p.id AND r.subscriber_id=?
             WHERE p.status='approved' AND p.effective_date<=?
             ORDER BY p.effective_date DESC,p.id DESC""",(sid,date.today().isoformat()))]

@router.post("/{policy_id}/read")
def mark_read(policy_id:int,x_notification_token:str|None=Header(None)):
    with _db() as c:
        sid=subscriber(c,x_notification_token)
        row=c.execute("SELECT id FROM policy_versions WHERE id=? AND status='approved' AND effective_date<=?",
                      (policy_id,date.today().isoformat())).fetchone()
        if not row: raise HTTPException(404,"Notification not available")
        c.execute("INSERT OR IGNORE INTO notification_reads(subscriber_id,policy_id) VALUES(?,?)",
                  (sid,policy_id))
    return {"read":True}

@router.delete("/subscription")
def unsubscribe(x_notification_token:str|None=Header(None)):
    with _db() as c:
        sid=subscriber(c,x_notification_token)
        c.execute("DELETE FROM notification_reads WHERE subscriber_id=?",(sid,))
        c.execute("DELETE FROM notification_subscribers WHERE id=?",(sid,))
    return {"unsubscribed":True}

@router.get("/admin/summary")
def summary(x_admin_key:str|None=Header(None)):
    _auth(x_admin_key)
    with _db() as c:
        return {"subscribers":c.execute("SELECT COUNT(*) FROM notification_subscribers").fetchone()[0],
                "read_receipts":c.execute("SELECT COUNT(*) FROM notification_reads").fetchone()[0]}
