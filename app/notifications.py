"""Opt-in in-app policy update inbox. No external email/SMS delivery."""
from datetime import date
from fastapi import APIRouter, HTTPException, Header
from . import auth as parent_auth

router=APIRouter(prefix="/api/notifications",tags=["notifications"])
_db=_auth=None

def configure(db,auth):
    global _db,_auth
    _db,_auth=db,auth

def setup(c):
    c.execute("""CREATE TABLE IF NOT EXISTS parent_notification_reads(
        parent_id INTEGER NOT NULL, policy_id INTEGER NOT NULL,
        read_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(parent_id,policy_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS notification_subscribers(
      id INTEGER PRIMARY KEY, token TEXT NOT NULL UNIQUE,
      label TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS notification_reads(
      subscriber_id INTEGER NOT NULL, policy_id INTEGER NOT NULL,
      read_at TEXT DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY(subscriber_id,policy_id))""")

# Legacy anonymous token subscriptions are retired. Existing rows remain in SQLite
# for a later, explicit data-retention migration; no public token endpoints remain.
@router.get("/admin/summary")
def summary(x_admin_key:str|None=Header(None)):
    _auth(x_admin_key)
    with _db() as c:
        return {"authenticated_parents":c.execute("SELECT COUNT(*) FROM parent_accounts WHERE enabled=1").fetchone()[0],
                "parent_read_receipts":c.execute("SELECT COUNT(*) FROM parent_notification_reads").fetchone()[0]}

# Authenticated parent inbox: read receipts are isolated by parent account.
@router.get("/mine")
def my_inbox(authorization:str|None=Header(None)):
    with _db() as c:
        p=parent_auth.parent(c,authorization)
        parent_auth.require_demo_school(p)
        return [dict(r) for r in c.execute("""SELECT p.id AS policy_id,p.policy_key,p.title,
            p.version,p.effective_date,
            CASE WHEN r.policy_id IS NULL THEN 0 ELSE 1 END AS is_read
            FROM policy_versions p LEFT JOIN parent_notification_reads r
              ON r.policy_id=p.id AND r.parent_id=?
            WHERE p.school_id=? AND p.status='approved' AND p.effective_date<=?
            ORDER BY p.effective_date DESC,p.id DESC""",
            (p["id"],p["school_id"],date.today().isoformat()))]

@router.post("/mine/{policy_id}/read")
def mark_my_read(policy_id:int,authorization:str|None=Header(None)):
    with _db() as c:
        p=parent_auth.parent(c,authorization)
        parent_auth.require_demo_school(p)
        found=c.execute("SELECT id FROM policy_versions WHERE id=? AND school_id=? AND status='approved' AND effective_date<=?",
                        (policy_id,p["school_id"],date.today().isoformat())).fetchone()
        if not found:raise HTTPException(404,"Notification not available")
        c.execute("INSERT OR IGNORE INTO parent_notification_reads(parent_id,policy_id) VALUES(?,?)",
                  (p["id"],policy_id))
    return {"read":True}
