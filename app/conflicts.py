"""Conservative knowledge conflict workflow.

Conflicts are candidate overlaps by explicit topic/key, not semantic proof of contradiction.
An unresolved overlap blocks policy approval until the admin deactivates the legacy item.
"""
import re
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/conflicts", tags=["conflicts"])
_db = _auth = _reindex = None

def configure(db, auth, reindex):
    global _db, _auth, _reindex
    _db, _auth, _reindex = db, auth, reindex

def setup(c):
    cols = {x["name"] for x in c.execute("PRAGMA table_info(knowledge)")}
    if "active" not in cols:
        c.execute("ALTER TABLE knowledge ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
    cols = {x["name"] for x in c.execute("PRAGMA table_info(documents)")}
    if "active" not in cols:
        c.execute("ALTER TABLE documents ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
    c.execute("""CREATE TABLE IF NOT EXISTS knowledge_conflicts(
        id INTEGER PRIMARY KEY, policy_id INTEGER NOT NULL,
        legacy_type TEXT NOT NULL CHECK(legacy_type IN ('faq','document')),
        legacy_id INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'open'
        CHECK(status IN ('open','resolved')), created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        resolved_at TEXT, UNIQUE(policy_id,legacy_type,legacy_id))""")

def norm(s):
    return re.sub(r"[^a-z0-9]+", "", s.lower())

def candidates(c, policy):
    """Flag explicit topic/key matches; document titles must match, not fuzzy tokens."""
    keys={norm(policy["policy_key"]),norm(policy["title"])}
    keys.discard("")
    result=[]
    for x in c.execute("SELECT id,topic FROM knowledge WHERE active=1"):
        if norm(x["topic"]) in keys:
            result.append(("faq",x["id"],x["topic"]))
    for x in c.execute("SELECT id,title FROM documents WHERE active=1"):
        if norm(x["title"]) in keys:
            result.append(("document",x["id"],x["title"]))
    return result

def scan(c, policy_id):
    p=c.execute("SELECT * FROM policy_versions WHERE id=?", (policy_id,)).fetchone()
    if not p: raise HTTPException(404,"Policy not found")
    for kind, id, _ in candidates(c,p):
        c.execute("""INSERT OR IGNORE INTO knowledge_conflicts(policy_id,legacy_type,legacy_id)
                     VALUES(?,?,?)""",(policy_id,kind,id))
    # Closed legacy sources resolve their conflicts; reactivation creates open conflicts.
    c.execute("""UPDATE knowledge_conflicts SET status='resolved',resolved_at=CURRENT_TIMESTAMP
        WHERE policy_id=? AND status='open' AND (
          (legacy_type='faq' AND NOT EXISTS(SELECT 1 FROM knowledge k WHERE k.id=legacy_id AND k.active=1))
          OR (legacy_type='document' AND NOT EXISTS(SELECT 1 FROM documents d WHERE d.id=legacy_id AND d.active=1))
        )""",(policy_id,))
    return c.execute("""SELECT id,legacy_type,legacy_id,status FROM knowledge_conflicts
                        WHERE policy_id=? ORDER BY id""",(policy_id,)).fetchall()

def pending(c, policy_id):
    scan(c,policy_id)
    return c.execute("SELECT COUNT(*) FROM knowledge_conflicts WHERE policy_id=? AND status='open'",(policy_id,)).fetchone()[0]

@router.get("")
def list_conflicts(x_admin_key: str | None=Header(None)):
    _auth(x_admin_key)
    with _db() as c:
        return [dict(r) for r in c.execute("""SELECT cf.*,p.policy_key,p.version,p.title AS policy_title
            FROM knowledge_conflicts cf JOIN policy_versions p ON p.id=cf.policy_id
            ORDER BY cf.id DESC""")]

@router.post("/scan/{policy_id}")
def scan_policy(policy_id:int,x_admin_key: str | None=Header(None)):
    _auth(x_admin_key)
    with _db() as c:
        items=scan(c,policy_id)
        return {"policy_id":policy_id,"conflicts":[dict(x) for x in items],
                "pending":sum(x["status"]=="open" for x in items)}

@router.post("/legacy/{kind}/{item_id}/deactivate")
def deactivate(kind:str,item_id:int,x_admin_key: str | None=Header(None)):
    _auth(x_admin_key)
    if kind not in ("faq","document"):raise HTTPException(422,"Invalid knowledge type")
    table="knowledge" if kind=="faq" else "documents"
    with _db() as c:
        if not c.execute(f"UPDATE {table} SET active=0 WHERE id=? AND active=1",(item_id,)).rowcount:
            raise HTTPException(404,"Active knowledge item not found")
        c.execute("""UPDATE knowledge_conflicts SET status='resolved',resolved_at=CURRENT_TIMESTAMP
            WHERE legacy_type=? AND legacy_id=? AND status='open'""",(kind,item_id))
    updated=_reindex()
    return {"deactivated":True,"vector_index_updated":updated}

@router.post("/legacy/{kind}/{item_id}/activate")
def activate(kind:str,item_id:int,x_admin_key: str | None=Header(None)):
    _auth(x_admin_key)
    if kind not in ("faq","document"):raise HTTPException(422,"Invalid knowledge type")
    table="knowledge" if kind=="faq" else "documents"
    with _db() as c:
        if not c.execute(f"UPDATE {table} SET active=1 WHERE id=? AND active=0",(item_id,)).rowcount:
            raise HTTPException(404,"Inactive knowledge item not found")
        # Reopening conflicts prevents silently reintroducing old facts.
        c.execute("""UPDATE knowledge_conflicts SET status='open',resolved_at=NULL
            WHERE legacy_type=? AND legacy_id=?""",(kind,item_id))
    updated=_reindex()
    return {"activated":True,"vector_index_updated":updated}
