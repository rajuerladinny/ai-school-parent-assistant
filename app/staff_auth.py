"""School-scoped staff accounts with hashed credentials and expiring bearer sessions.

Legacy shared-key staff endpoints remain demo-only and must be retired before production.
"""
import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime,timedelta,timezone
from . import shared_login_limit
from fastapi import APIRouter,Header,HTTPException,Request
from pydantic import BaseModel,Field
from .auth import digest

router=APIRouter(prefix="/api/staff-auth",tags=["staff-auth"])
_attempts={}
_attempt_lock=threading.Lock()
_WINDOW=300
_LIMIT=5

def _limit_login(username,ip):
    now=time.monotonic()
    key=(ip,username.lower())
    with _attempt_lock:
        for old,(start,_) in list(_attempts.items()):
            if now-start>_WINDOW:del _attempts[old]
        start,count=_attempts.get(key,(now,0))
        if count>=_LIMIT:
            raise HTTPException(429,"Too many login attempts; try again later",headers={"Retry-After":str(_WINDOW)})
        _attempts[key]=(start,count+1)

def _clear_login(username,ip):
    with _attempt_lock:_attempts.pop((ip,username.lower()),None)

_db=_admin=None

def configure(db,admin):
    global _db,_admin
    _db,_admin=db,admin

def setup(c):
    c.execute("""CREATE TABLE IF NOT EXISTS staff_accounts(
        id INTEGER PRIMARY KEY, school_id INTEGER NOT NULL REFERENCES schools(id),
        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        display_name TEXT NOT NULL,salt TEXT NOT NULL,password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('school_admin','staff')),
        enabled INTEGER NOT NULL DEFAULT 1,created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS staff_sessions(
        token_hash TEXT PRIMARY KEY,staff_id INTEGER NOT NULL REFERENCES staff_accounts(id),
        expires_at TEXT NOT NULL)""")

class StaffAccount(BaseModel):
    username:str=Field(min_length=3,max_length=80,pattern=r"^[a-zA-Z0-9_.-]+$")
    display_name:str=Field(min_length=2,max_length=80)
    password:str=Field(min_length=12,max_length=128)
    school_id:int=Field(default=1,ge=1)
    role:str=Field(pattern=r"^(school_admin|staff)$")

class Credentials(BaseModel):
    # Bound untrusted login payloads before expensive password hashing or Redis calls.
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)

@router.post("/accounts",status_code=201)
def create_account(item:StaffAccount,x_admin_key:str|None=Header(None)):
    _admin(x_admin_key)
    salt=secrets.token_hex(16)
    with _db() as c:
        if not c.execute("SELECT 1 FROM schools WHERE id=? AND active=TRUE",(item.school_id,)).fetchone():
            raise HTTPException(404,"School not found")
        cur=c.execute("""INSERT INTO staff_accounts(school_id,username,display_name,salt,password_hash,role)
            VALUES(?,?,?,?,?,?) ON CONFLICT DO NOTHING RETURNING id""",(item.school_id,item.username.lower(),item.display_name,salt,digest(item.password,salt),item.role))
        row=cur.fetchone()
        if row is None:
            raise HTTPException(409,"Username already exists")
        return {"id":row["id"],"school_id":item.school_id,"role":item.role}

@router.post("/login")
def login(item:Credentials,request:Request):
    ip=request.client.host if request.client else "unknown"
    if not shared_login_limit.check('staff',item.username,ip):
        _limit_login(item.username,ip)
    with _db() as c:
        account=c.execute("""SELECT a.* FROM staff_accounts a
            JOIN schools sc ON sc.id=a.school_id
            WHERE a.username=? AND sc.active=TRUE""",(item.username.lower(),)).fetchone()
        if not account or not account["enabled"] or not hmac.compare_digest(
                digest(item.password,account["salt"]),account["password_hash"]):
            raise HTTPException(401,"Invalid credentials")
        token=secrets.token_urlsafe(32)
        expires=(datetime.now(timezone.utc)+timedelta(hours=8)).isoformat()
        c.execute("INSERT INTO staff_sessions(token_hash,staff_id,expires_at) VALUES(?,?,?)",
                  (hashlib.sha256(token.encode()).hexdigest(),account["id"],expires))
    _clear_login(item.username,ip)
    return {"access_token":token,"token_type":"bearer","expires_at":expires,"role":account["role"]}

def principal(c,authorization,roles=("school_admin","staff")):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401,"Staff login required")
    row=c.execute("""SELECT a.id,a.school_id,a.username,a.display_name,a.role FROM staff_sessions s
        JOIN staff_accounts a ON a.id=s.staff_id JOIN schools sc ON sc.id=a.school_id
        WHERE s.token_hash=? AND s.expires_at>? AND a.enabled=TRUE AND sc.active=TRUE""",
        (hashlib.sha256(authorization[7:].encode()).hexdigest(),datetime.now(timezone.utc).isoformat())).fetchone()
    if not row:raise HTTPException(401,"Invalid or expired staff session")
    if row["role"] not in roles:raise HTTPException(403,"Insufficient staff permissions")
    return row

@router.get("/me")
def me(authorization:str|None=Header(None)):
    with _db() as c:return dict(principal(c,authorization))

@router.post("/logout")
def logout(authorization:str|None=Header(None)):
    with _db() as c:
        principal(c,authorization)
        c.execute("DELETE FROM staff_sessions WHERE token_hash=?",
                  (hashlib.sha256(authorization[7:].encode()).hexdigest(),))
    return {"logged_out":True}
