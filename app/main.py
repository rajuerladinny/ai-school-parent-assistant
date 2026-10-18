import os, sqlite3, secrets, re
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

app=FastAPI(title="School Parent Assistant")
DB=os.getenv("SCHOOL_DB","school.db")
SAMPLE=[
("Timings","School hours are Monday to Friday, 8:30 AM to 3:30 PM.","Sample school handbook"),
("Holidays","No confirmed holiday calendar is available in this demo. Ask the school office for a specific date.","Sample school calendar"),
("Admissions","Contact the school office during office hours for the admissions process.","Admissions office"),
("Fees","Contact the school office for payment deadlines and approved payment methods.","Fees office"),
("Events","No upcoming events have been published in this demo.","Events calendar"),
("Contact","Contact the school office between 9 AM and 4 PM on weekdays.","School handbook")]
def db():
    c=sqlite3.connect(DB);c.row_factory=sqlite3.Row;return c
def setup():
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS knowledge(id INTEGER PRIMARY KEY, topic TEXT, answer TEXT, source TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS escalations(id INTEGER PRIMARY KEY, question TEXT, status TEXT DEFAULT 'open')")
        if not c.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]:
            c.executemany("INSERT INTO knowledge(topic,answer,source) VALUES(?,?,?)",SAMPLE)
@app.on_event("startup")
def startup():setup()
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
@app.get("/api/knowledge")
def knowledge():
    with db() as c:return [dict(x) for x in c.execute("SELECT * FROM knowledge ORDER BY id")]
@app.post("/api/knowledge",status_code=201)
def add(item:Item,x_admin_key:str|None=Header(None)):
    auth(x_admin_key)
    with db() as c:
        cur=c.execute("INSERT INTO knowledge(topic,answer,source) VALUES(?,?,?)",tuple(item.model_dump().values()))
        return {"id":cur.lastrowid}
@app.delete("/api/knowledge/{id}")
def delete(id:int,x_admin_key:str|None=Header(None)):
    auth(x_admin_key)
    with db() as c:
        if not c.execute("DELETE FROM knowledge WHERE id=?",(id,)).rowcount:raise HTTPException(404,"Not found")
    return {"deleted":True}
@app.post("/api/chat")
def chat(q:Question):
    words=set(re.findall(r"[a-z]{3,}",q.question.lower()))-{"what","when","where","will","school","please","about","today","tomorrow","there","have","the","for","are","can","you"}
    with db() as c:
        ranked=[]
        for row in c.execute("SELECT * FROM knowledge"):
            topic=set(re.findall(r"[a-z]{3,}",row["topic"].lower()))
            score=4*len(words&topic)
            if score:ranked.append((score,dict(row)))
        if ranked:
            match=max(ranked,key=lambda x:x[0])[1]
            return {"answer":match["answer"],"source":match["source"],"needs_staff":False}
        c.execute("INSERT INTO escalations(question) VALUES(?)",(q.question,))
        return {"answer":"I don't have verified information for that. Your question has been sent for school staff review.","source":None,"needs_staff":True}
@app.get("/api/escalations")
def escalations(x_admin_key:str|None=Header(None)):
    auth(x_admin_key)
    with db() as c:return [dict(x) for x in c.execute("SELECT * FROM escalations ORDER BY id DESC")]
@app.get("/",response_class=HTMLResponse)
def home():return Path(__file__).with_name("index.html").read_text()
