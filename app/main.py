import os, sqlite3, secrets, re, io
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from . import rag

app=FastAPI(title="School Parent Assistant with RAG")
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
    c=sqlite3.connect(DB);c.row_factory=sqlite3.Row;return c
def records_for_index():
    with db() as c:
        records=[]
        for r in c.execute("SELECT id,topic,answer,source FROM knowledge"):
            records.append({"id":"faq-"+str(r["id"]),"topic":r["topic"],"source":r["source"],
                            "text":r["topic"]+"\n"+r["answer"]})
        for r in c.execute("SELECT id,filename,title,content FROM documents"):
            records.append({"id":"doc-"+str(r["id"]),"topic":r["title"],
                            "source":r["filename"],"text":r["content"]})
        return records
def rebuild_index():
    return rag.rebuild(records_for_index())
def setup():
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS knowledge(id INTEGER PRIMARY KEY, topic TEXT, answer TEXT, source TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS escalations(id INTEGER PRIMARY KEY, question TEXT, status TEXT DEFAULT 'open', created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        c.execute("""CREATE TABLE IF NOT EXISTS documents(
            id INTEGER PRIMARY KEY, filename TEXT NOT NULL, title TEXT NOT NULL,
            content TEXT NOT NULL, uploaded_at TEXT NOT NULL)""")
        if not c.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]:
            c.executemany("INSERT INTO knowledge(topic,answer,source) VALUES(?,?,?)",SAMPLE)
@app.on_event("startup")
def startup():
    setup()
    rebuild_index()
class Item(BaseModel):
    topic:str=Field(min_length=2,max_length=100)
    answer:str=Field(min_length=5,max_length=2000)
    source:str=Field(min_length=2,max_length=150)
class Question(BaseModel):
    question:str=Field(min_length=3,max_length=500)
def auth(key):
    secret=os.getenv("SCHOOL_ADMIN_KEY","")
    if not secret:raise HTTPException(503,"Configure SCHOOL_ADMIN_KEY")
    if not key or not secrets.compare_digest(key,secret):raise HTTPException(401,"Invalid admin key")
def fallback_search(question):
    words=set(re.findall(r"[a-z]{3,}",question.lower()))-{"what","when","where","will","school","please","about","today","tomorrow","there","have","the","for","are","can","you"}
    with db() as c:
        ranked=[]
        for row in c.execute("SELECT * FROM knowledge"):
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
def knowledge():
    with db() as c:return [dict(x) for x in c.execute("SELECT * FROM knowledge ORDER BY id")]
@app.post("/api/knowledge",status_code=201)
def add(item:Item,x_admin_key:str|None=Header(None)):
    auth(x_admin_key)
    with db() as c:
        cur=c.execute("INSERT INTO knowledge(topic,answer,source) VALUES(?,?,?)",tuple(item.model_dump().values()))
        item_id=cur.lastrowid
    rebuild_index()
    return {"id":item_id,"vector_index_updated":rag.enabled()}
@app.delete("/api/knowledge/{id}")
def delete(id:int,x_admin_key:str|None=Header(None)):
    auth(x_admin_key)
    with db() as c:
        if not c.execute("DELETE FROM knowledge WHERE id=?",(id,)).rowcount:raise HTTPException(404,"Not found")
    rebuild_index()
    return {"deleted":True}
@app.get("/api/documents")
def documents(x_admin_key:str|None=Header(None)):
    auth(x_admin_key)
    with db() as c:
        return [dict(x) for x in c.execute("SELECT id,filename,title,uploaded_at,length(content) AS characters FROM documents ORDER BY id DESC")]
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
        cur=c.execute("INSERT INTO documents(filename,title,content,uploaded_at) VALUES(?,?,?,?)",
                      (filename,clean_title,text,datetime.now(timezone.utc).isoformat()))
        doc_id=cur.lastrowid
    indexed=rebuild_index()
    return {"id":doc_id,"filename":filename,"characters":len(text),"vector_index_updated":indexed,
            "note":"Document is searchable after indexing. Review the source content before relying on answers."}
@app.delete("/api/documents/{id}")
def delete_document(id:int,x_admin_key:str|None=Header(None)):
    auth(x_admin_key)
    with db() as c:
        if not c.execute("DELETE FROM documents WHERE id=?",(id,)).rowcount:raise HTTPException(404,"Document not found")
    rebuild_index()
    return {"deleted":True}
@app.post("/api/chat")
def chat(q:Question):
    results=rag.search(q.question,limit=4)
    # Avoid confident answers when semantic matches are weak.
    relevant=[r for r in results if r.get("distance",1.0)<=float(os.getenv("RAG_MAX_DISTANCE","0.62"))]
    if relevant:
        answer, generator=generate_grounded_answer(q.question,relevant)
        return {"answer":answer,"source":", ".join(dict.fromkeys(r["source"] for r in relevant)),
                "sources":[{"source":r["source"],"topic":r["topic"],"distance":round(r["distance"],3)} for r in relevant],
                "needs_staff":False,"retrieval":"chroma-vector","generator":generator}
    fallback=fallback_search(q.question)
    if fallback:return fallback
    with db() as c:c.execute("INSERT INTO escalations(question) VALUES(?)",(q.question,))
    return {"answer":"I don't have verified information for that. Your question has been sent for school staff review.",
            "source":None,"needs_staff":True,"retrieval":"no-confident-match"}
@app.get("/api/escalations")
def escalations(x_admin_key:str|None=Header(None)):
    auth(x_admin_key)
    with db() as c:return [dict(x) for x in c.execute("SELECT * FROM escalations ORDER BY id DESC")]
@app.get("/",response_class=HTMLResponse)
def home():return Path(__file__).with_name("index.html").read_text()
