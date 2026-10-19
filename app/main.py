import os, sqlite3, secrets, re, io
from datetime import datetime, timezone, date
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from pydantic import BaseModel, Field
from . import rag, policies, conflicts, notifications, auth as parent_auth, staff, staff_auth, parent_questions, database_config, school_admin

_last_policy_index_date = None

app=FastAPI(title="School Parent Assistant with RAG",
            docs_url=None if os.getenv("SCHOOL_ENV")=="production" else "/docs",
            redoc_url=None if os.getenv("SCHOOL_ENV")=="production" else "/redoc")
if os.getenv("SCHOOL_ENV")=="production":
    if not os.getenv("SCHOOL_ADMIN_KEY") or len(os.environ["SCHOOL_ADMIN_KEY"])<32:
        raise RuntimeError("Production requires a random SCHOOL_ADMIN_KEY of at least 32 characters")
    hosts=[x.strip() for x in os.getenv("SCHOOL_ALLOWED_HOSTS","").split(",") if x.strip()]
    if not hosts or "*" in hosts:
        raise RuntimeError("Production requires explicit SCHOOL_ALLOWED_HOSTS")
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=hosts)
    if os.getenv("SCHOOL_ENFORCE_HTTPS")!="1":
        raise RuntimeError("Production requires SCHOOL_ENFORCE_HTTPS=1")
    app.add_middleware(HTTPSRedirectMiddleware)
    # In-memory login counters are process-local and cannot enforce limits
    # across production workers. Refuse deployment until a shared limiter exists.
    raise RuntimeError("Production blocked: shared login rate limiter is not implemented")

@app.middleware("http")
async def response_headers(request:Request,call_next):
    response=await call_next(request)
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["Referrer-Policy"]="no-referrer"
    response.headers["X-Frame-Options"]="DENY"
    response.headers["Content-Security-Policy"]="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    response.headers["Cache-Control"]="no-store"
    return response
DB=os.getenv("SCHOOL_DB","school.db")
MAX_UPLOAD=5*1024*1024
SAMPLE=[
("Timings","School hours are Monday to Friday, 8:30 AM to 3:30 PM.","Sample school handbook"),
("Holidays","No confirmed holiday calendar is available in this demo. Ask the school office for a specific date.","Sample school calendar"),
("Admissions","Contact the school office during office hours for the admissions process.","Admissions office"),
("Fees","Contact the school office for payment deadlines and approved payment methods.","Fees office"),
("Events","No upcoming events have been published in this demo.","Events calendar"),
("Contact","Contact the school office between 9 AM and 4 PM on weekdays.","School handbook")]
def db():
    if database_config.backend()=="postgres":
        from .postgres_adapter import connect
        return connect(os.environ["SCHOOL_POSTGRES_DSN"])
    c=sqlite3.connect(DB,timeout=10);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA busy_timeout=10000');return c
def records_for_index():
    with db() as c:
        records=[]
        for r in c.execute("SELECT id,topic,answer,source,school_id FROM knowledge WHERE active=TRUE"):
            records.append({"id":"faq-"+str(r["id"]),"school_id":r["school_id"],"topic":r["topic"],"source":r["source"],
                            "text":r["topic"]+"\n"+r["answer"]})
        for r in c.execute("SELECT id,filename,title,content,school_id FROM documents WHERE active=TRUE"):
            records.append({"id":"doc-"+str(r["id"]),"school_id":r["school_id"],"topic":r["title"],
                            "source":r["filename"],"text":r["content"]})
        records.extend({**r,"school_id":1} for r in policies.active_records(c))
        return records
def rebuild_index():
    global _last_policy_index_date
    updated = rag.rebuild(records_for_index())
    if updated:
        _last_policy_index_date = date.today().isoformat()
    return updated

def ensure_current_policy_index():
    if _last_policy_index_date != date.today().isoformat():
        rebuild_index()
def setup():
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS knowledge(id INTEGER PRIMARY KEY, topic TEXT, answer TEXT, source TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS escalations(id INTEGER PRIMARY KEY, question TEXT, status TEXT DEFAULT 'open', created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        c.execute("""CREATE TABLE IF NOT EXISTS documents(
            id INTEGER PRIMARY KEY, filename TEXT NOT NULL, title TEXT NOT NULL,
            content TEXT NOT NULL, uploaded_at TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS schools(
            id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1)""")
        c.execute("INSERT INTO schools(id,slug,name) VALUES(1,'demo','Sunrise Valley School (demo)') ON CONFLICT DO NOTHING")
        for table in ("knowledge","documents"):
            cols={r[1] for r in c.execute(f"PRAGMA table_info({table})")}
            if "school_id" not in cols:
                c.execute(f"ALTER TABLE {table} ADD COLUMN school_id INTEGER NOT NULL DEFAULT 1 REFERENCES schools(id)")
            c.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_school ON {table}(school_id)")
        policies.setup(c)
        conflicts.setup(c)
        notifications.setup(c)
        parent_auth.setup(c)
        cols={r[1] for r in c.execute("PRAGMA table_info(parent_accounts)")}
        if "school_id" not in cols:
            c.execute("ALTER TABLE parent_accounts ADD COLUMN school_id INTEGER NOT NULL DEFAULT 1 REFERENCES schools(id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_parent_accounts_school ON parent_accounts(school_id)")
        cols={r[1] for r in c.execute("PRAGMA table_info(escalations)")}
        if "school_id" not in cols:
            c.execute("ALTER TABLE escalations ADD COLUMN school_id INTEGER NOT NULL DEFAULT 1 REFERENCES schools(id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_escalations_school ON escalations(school_id,status)")
        staff.setup(c)
        staff_auth.setup(c)
        parent_questions.setup(c)
        if not c.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]:
            c.executemany("INSERT INTO knowledge(topic,answer,source) VALUES(?,?,?)",SAMPLE)
@app.on_event("startup")
def startup():
    database_config.validate_configuration()
    if database_config.backend()=="sqlite" and os.getenv("SCHOOL_ENV")=="production" and os.getenv("SCHOOL_DB","school.db").endswith(".db"):
        raise RuntimeError("SQLite production mode is disabled until PostgreSQL migration is complete")
    if database_config.backend()=="postgres":
        from scripts.postgres_bootstrap import validate
        validate(os.environ["SCHOOL_POSTGRES_DSN"])
        # PostgreSQL schema is managed externally; never execute SQLite DDL or seed data.
    else:
        setup()
    rebuild_index()
class Item(BaseModel):
    topic:str=Field(min_length=2,max_length=100)
    answer:str=Field(min_length=5,max_length=2000)
    source:str=Field(min_length=2,max_length=150)
class Question(BaseModel):
    question:str=Field(min_length=3,max_length=500)
def auth(key):
    # The shared bootstrap key has no school identity or RBAC claims.
    # Reject it for every legacy admin endpoint in production.
    if os.getenv("SCHOOL_ENV")=="production":
        raise HTTPException(403,"Legacy shared-key admin API is disabled in production")
    secret=os.getenv("SCHOOL_ADMIN_KEY","")
    if not secret:raise HTTPException(503,"Configure SCHOOL_ADMIN_KEY")
    if not key or not secrets.compare_digest(key,secret):raise HTTPException(401,"Invalid admin key")
def fallback_search(question,school_id=1):
    words=set(re.findall(r"[a-z]{3,}",question.lower()))-{"what","when","where","will","school","please","about","today","tomorrow","there","have","the","for","are","can","you"}
    with db() as c:
        ranked=[]
        for row in c.execute("SELECT * FROM knowledge WHERE active=TRUE AND school_id=?",(school_id,)):
            topic=set(re.findall(r"[a-z]{3,}",row["topic"].lower()))
            score=4*len(words&topic)
            if score:ranked.append((score,dict(row)))
        if ranked:
            match=max(ranked,key=lambda x:x[0])[1]
            return {"answer":match["answer"],"source":match["source"],"needs_staff":False,"retrieval":"keyword-fallback"}
    return None
def generate_grounded_answer(question, passages):
    context="\n\n".join(f"Source: {p['source']}\nTopic: {p['topic']}\nExcerpt: {p['text']}" for p in passages)
    base=os.getenv("OLLAMA_BASE_URL","").rstrip("/")
    model=os.getenv("OLLAMA_MODEL","llama3.2:3b")
    if base:
        try:
            import httpx
            response=httpx.post(base+"/api/generate",json={
                "model":model,"stream":False,
                "prompt":("Answer the parent's question using only the school excerpts below. "
                          "If the excerpts do not clearly answer, say you do not have verified information "
                          "and recommend contacting school staff. Never invent fees, dates, rules or policies. "
                          "Keep the answer concise.\n\nSCHOOL EXCERPTS:\n"+context+
                          "\n\nPARENT QUESTION: "+question+"\nANSWER:"),
                "options":{"temperature":0.1}},timeout=40)
            response.raise_for_status()
            answer=response.json().get("response","").strip()
            if answer:return answer,"ollama:"+model
        except Exception:
            pass
    # No local generator configured: return retrieved excerpts transparently, not a fabricated AI answer.
    return "\n\n".join(p["text"] for p in passages[:2]),"extractive-rag"
@app.get("/api/health")
def health():
    return {"status":"ok","vector_search_enabled":rag.enabled(),"local_generator_configured":bool(os.getenv("OLLAMA_BASE_URL"))}
@app.get("/api/knowledge")
def knowledge(x_admin_key:str|None=Header(None)):
    auth(x_admin_key)
    with db() as c:return [dict(x) for x in c.execute("SELECT * FROM knowledge WHERE school_id=1 ORDER BY id")]
@app.post("/api/knowledge",status_code=201)
def add(item:Item,x_admin_key:str|None=Header(None)):
    auth(x_admin_key)
    with db() as c:
        cur=c.execute("INSERT INTO knowledge(topic,answer,source,school_id) VALUES(?,?,?,1) RETURNING id",tuple(item.model_dump().values()))
        item_id=cur.fetchone()["id"]
    rebuild_index()
    return {"id":item_id,"vector_index_updated":rag.enabled()}
@app.delete("/api/knowledge/{id}")
def delete(id:int,x_admin_key:str|None=Header(None)):
    auth(x_admin_key)
    with db() as c:
        if not c.execute("DELETE FROM knowledge WHERE id=? AND school_id=1",(id,)).rowcount:raise HTTPException(404,"Not found")
    rebuild_index()
    return {"deleted":True}
@app.get("/api/documents")
def documents(x_admin_key:str|None=Header(None)):
    auth(x_admin_key)
    with db() as c:
        return [dict(x) for x in c.execute("SELECT id,filename,title,active,uploaded_at,length(content) AS characters FROM documents WHERE school_id=1 ORDER BY id DESC")]
def extract_text(filename, data):
    suffix=Path(filename).suffix.lower()
    if suffix in (".txt",".md"):
        try:return data.decode("utf-8-sig")
        except UnicodeDecodeError:raise HTTPException(400,"Text file must use UTF-8 encoding")
    if suffix==".pdf":
        try:
            from pypdf import PdfReader
            reader=PdfReader(io.BytesIO(data))
            if len(reader.pages)>100:raise HTTPException(400,"PDF is limited to 100 pages")
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:raise HTTPException(503,"PDF support not installed. Install requirements-rag.txt")
        except HTTPException:raise
        except Exception:raise HTTPException(400,"Could not read this PDF; it may be scanned or damaged")
    if suffix==".docx":
        try:
            from docx import Document
            doc=Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs)
        except ImportError:raise HTTPException(503,"DOCX support not installed. Install requirements-rag.txt")
        except Exception:raise HTTPException(400,"Could not read this DOCX file")
    raise HTTPException(415,"Supported file types: PDF, DOCX, TXT, MD")
@app.post("/api/documents",status_code=201)
async def upload_document(file:UploadFile=File(...),title:str=Form("School document"),x_admin_key:str|None=Header(None)):
    auth(x_admin_key)
    filename=Path(file.filename or "").name
    if not filename or len(filename)>180:raise HTTPException(400,"Invalid filename")
    data=await file.read(MAX_UPLOAD+1)
    if len(data)>MAX_UPLOAD:raise HTTPException(413,"Maximum upload size is 5 MB")
    text=extract_text(filename,data).strip()
    if len(text)<30:raise HTTPException(400,"Document contains too little extractable text")
    if len(text)>2_000_000:raise HTTPException(413,"Extracted document text is too large")
    clean_title=title.strip()[:150] or filename
    with db() as c:
        cur=c.execute("INSERT INTO documents(filename,title,content,uploaded_at,school_id) VALUES(?,?,?,?,1) RETURNING id",
                      (filename,clean_title,text,datetime.now(timezone.utc).isoformat()))
        doc_id=cur.fetchone()["id"]
    indexed=rebuild_index()
    return {"id":doc_id,"filename":filename,"characters":len(text),"vector_index_updated":indexed,
            "note":"Document is searchable after indexing. Review the source content before relying on answers."}
@app.delete("/api/documents/{id}")
def delete_document(id:int,x_admin_key:str|None=Header(None)):
    auth(x_admin_key)
    with db() as c:
        if not c.execute("DELETE FROM documents WHERE id=? AND school_id=1",(id,)).rowcount:raise HTTPException(404,"Document not found")
    rebuild_index()
    return {"deleted":True}
@app.post("/api/chat")
def chat(q:Question,authorization:str|None=Header(None)):
    if os.getenv("SCHOOL_ENV")=="production" and not authorization:
        raise HTTPException(401,"Parent login required")
    school_id=1
    parent_id=None
    if authorization:
        with db() as c:
            principal=parent_auth.parent(c,authorization)
            school_id=principal["school_id"]
            parent_id=principal["id"]
    ensure_current_policy_index()
    results=rag.search(q.question,limit=4,school_id=school_id)
    # Avoid confident answers when semantic matches are weak.
    relevant=[r for r in results if r.get("distance",1.0)<=float(os.getenv("RAG_MAX_DISTANCE","0.62"))]
    if relevant:
        answer, generator=generate_grounded_answer(q.question,relevant)
        return {"answer":answer,"source":", ".join(dict.fromkeys(r["source"] for r in relevant)),
                "sources":[{"source":r["source"],"topic":r["topic"],"distance":round(r["distance"],3)} for r in relevant],
                "needs_staff":False,"retrieval":"chroma-vector","generator":generator}
    # Once semantic search is active, do not override a weak vector match with
    # keyword matching; that could turn an unrelated FAQ into a confident answer.
    if not rag.enabled():
        fallback=fallback_search(q.question,school_id=school_id)
        if fallback:return fallback
    with db() as c:
        cur=c.execute("INSERT INTO escalations(question,parent_id,school_id) VALUES(?,?,?) RETURNING id",(q.question,parent_id,school_id))
        escalation_id=cur.fetchone()["id"]
    return {"answer":"I don't have verified information for that. Your question has been sent for school staff review.",
            "source":None,"needs_staff":True,"retrieval":"no-confident-match","escalation_id":escalation_id}
@app.get("/api/escalations")
def escalations(x_admin_key:str|None=Header(None)):
    auth(x_admin_key)
    with db() as c:return [dict(x) for x in c.execute("SELECT * FROM escalations WHERE school_id=1 ORDER BY id DESC")]
@app.get("/",response_class=HTMLResponse)
def home():return Path(__file__).with_name("index.html").read_text()

# Policy module uses the same admin key, SQLite store and document parser.
policies.configure(db, auth, extract_text, rebuild_index)
app.include_router(policies.router)

conflicts.configure(db, auth, rebuild_index)
app.include_router(conflicts.router)

notifications.configure(db, auth)
app.include_router(notifications.router)

parent_auth.configure(db, auth)
app.include_router(parent_auth.router)

staff.configure(db, auth)
app.include_router(staff.router)

parent_questions.configure(db)
app.include_router(parent_questions.router)

# School-specific staff login and identity API.
staff_auth.configure(db,auth)
app.include_router(staff_auth.router)

# Bearer-authenticated, tenant-scoped administrative replacement API.
school_admin.configure(db,rebuild_index,extract_text)
app.include_router(school_admin.router)
