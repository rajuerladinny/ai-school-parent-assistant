"""School-managed parent accounts with scrypt password hashing and expiring sessions.

This is a demo authentication layer; production needs TLS, rate limiting, password
reset and a dedicated identity provider. Parents cannot self-register.
"""
import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Header, Request
from pydantic import BaseModel, Field

router=APIRouter(prefix="/api/auth",tags=["auth"])
_db=_admin=None
_login_attempts={}
_login_lock=threading.Lock()
_LOGIN_WINDOW_SECONDS=300
_LOGIN_MAX_ATTEMPTS=5

def _check_login_limit(username,ip):
    now=time.monotonic()
    key=(ip,username.lower())
    with _login_lock:
        for k,v in list(_login_attempts.items()):
            if now-v[0]>_LOGIN_WINDOW_SECONDS:
                del _login_attempts[k]
        start,count=_login_attempts.get(key,(now,0))
        if count>=_LOGIN_MAX_ATTEMPTS:
            raise HTTPException(429,"Too many login attempts; try again later",headers={"Retry-After":str(_LOGIN_WINDOW_SECONDS)})
        _login_attempts[key]=(start,count+1)

def _clear_login_limit(username,ip):
    with _login_lock:
        _login_attempts.pop((ip,username.lower()),None)


def configure(db,admin):
    global _db,_admin
    _db,_admin=db,admin

def setup(c):
    c.execute("""CREATE TABLE IF NOT EXISTS parent_accounts(
        id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        display_name TEXT NOT NULL, salt TEXT NOT NULL, password_hash TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS parent_sessions(
        token_hash TEXT PRIMARY KEY, parent_id INTEGER NOT NULL,
        expires_at TEXT NOT NULL, FOREIGN KEY(parent_id) REFERENCES parent_accounts(id))""")

def digest(password,salt):
    return hashlib.scrypt(password.encode("utf-8"),salt=bytes.fromhex(salt),
                          n=2**14,r=8,p=1).hex()

class CreateParent(BaseModel):
    username:str=Field(min_length=3,max_length=80,pattern=r"^[a-zA-Z0-9_.-]+$")
    display_name:str=Field(min_length=2,max_length=80)
    password:str=Field(min_length=12,max_length=128)

class Credentials(BaseModel):
    username:str
    password:str

@router.post("/parents",status_code=201)
def create_parent(item:CreateParent,x_admin_key:str|None=Header(None)):
    _admin(x_admin_key)
    salt=secrets.token_hex(16)
    with _db() as c:
        try:
            cur=c.execute("INSERT INTO parent_accounts(username,display_name,salt,password_hash) VALUES(?,?,?,?)",
                          (item.username.lower(),item.display_name.strip(),salt,digest(item.password,salt)))
        except __import__("sqlite3").IntegrityError:
            raise HTTPException(409,"Username already exists")
        return {"id":cur.lastrowid,"username":item.username.lower(),"role":"parent"}

@router.post("/login")
def login(item:Credentials,request:Request):
    ip=request.client.host if request.client else 'unknown'
    _check_login_limit(item.username,ip)
    with _db() as c:
        row=c.execute("SELECT * FROM parent_accounts WHERE username=?",(item.username,)).fetchone()
        # Same generic error for unknown user, wrong password, or disabled account.
        if not row or not row["enabled"] or not hmac.compare_digest(
            digest(item.password,row["salt"]),row["password_hash"]):
            raise HTTPException(401,"Invalid credentials")
        token=secrets.token_urlsafe(32)
        expiry=(datetime.now(timezone.utc)+timedelta(hours=12)).isoformat()
        c.execute("INSERT INTO parent_sessions(token_hash,parent_id,expires_at) VALUES(?,?,?)",
                  (hashlib.sha256(token.encode()).hexdigest(),row["id"],expiry))
    _clear_login_limit(item.username,ip)
    return {"access_token":token,"token_type":"bearer","expires_at":expiry,"role":"parent"}

def parent(c,authorization):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401,"Parent login required")
    token=authorization[7:]
    if not token:raise HTTPException(401,"Parent login required")
    hashed=hashlib.sha256(token.encode()).hexdigest()
    row=c.execute("""SELECT a.id,a.username,a.display_name FROM parent_sessions s
       JOIN parent_accounts a ON a.id=s.parent_id
       WHERE s.token_hash=? AND s.expires_at>? AND a.enabled=1""",
       (hashed,datetime.now(timezone.utc).isoformat())).fetchone()
    if not row:raise HTTPException(401,"Invalid or expired session")
    return row

@router.get("/me")
def me(authorization:str|None=Header(None)):
    with _db() as c:
        p=parent(c,authorization)
        return {"id":p["id"],"username":p["username"],"display_name":p["display_name"],"role":"parent"}

@router.post("/logout")
def logout(authorization:str|None=Header(None)):
    with _db() as c:
        parent(c,authorization)
        c.execute("DELETE FROM parent_sessions WHERE token_hash=?",
                  (hashlib.sha256(authorization[7:].encode()).hexdigest(),))
    return {"logged_out":True}

@router.post("/parents/{parent_id}/disable")
def disable(parent_id:int,x_admin_key:str|None=Header(None)):
    _admin(x_admin_key)
    with _db() as c:
        if not c.execute("UPDATE parent_accounts SET enabled=0 WHERE id=? AND enabled=1",
                         (parent_id,)).rowcount:raise HTTPException(404,"Enabled parent not found")
        c.execute("DELETE FROM parent_sessions WHERE parent_id=?",(parent_id,))
    return {"disabled":True}
