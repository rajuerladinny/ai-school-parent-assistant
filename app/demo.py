"""Public demo mode: fictional seed data, a read-only staff portal and no stored visitor input.

Enable with SCHOOL_DEMO_MODE=1 for a hosted showcase (for example a Hugging Face Space).
Everything here is fictional Sunrise Valley School data. Demo mode refuses to run in
production and must never be pointed at a database that holds real records.
"""
import os
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse

DEMO_DOCS = Path(__file__).resolve().parent.parent / "docs" / "demo"

# Publicly documented demo values (also listed in docs/demo/DEMO_GUIDE.md).
PARENT_USERNAME = "priya.demo"
PARENT_PASSWORD = "SunriseDemo#2026"
PARENT_DISPLAY_NAME = "Priya Sharma"
SCHOOL_CODE = "demo"

READ_ONLY_MESSAGE = ("This public demo is read-only, so staff changes are switched off. "
                     "Run the project locally to try uploads, approvals and replies.")

# Requests a visitor may still make in demo mode: asking, signing in and out,
# and marking a policy update as read. Everything else that changes data is blocked.
_ALLOWED_WRITES = [
    re.compile(r"^/api/chat$"),
    re.compile(r"^/api/auth/login$"),
    re.compile(r"^/api/auth/logout$"),
    re.compile(r"^/api/notifications/mine/\d+/read$"),
]

SAMPLE_QUESTIONS = [
    "Is the school nut-free?",
    "When do after-school clubs run?",
    "What should my child wear to school?",
    "Is there a sibling discount on fees?",
    "Can my son bring his pet rabbit to show and tell?",
]


def enabled() -> bool:
    return os.getenv("SCHOOL_DEMO_MODE") == "1"


def validate() -> None:
    if not enabled():
        return
    if os.getenv("SCHOOL_ENV") == "production":
        raise RuntimeError("SCHOOL_DEMO_MODE cannot be used with SCHOOL_ENV=production")
    if not os.getenv("SCHOOL_ADMIN_KEY"):
        raise RuntimeError("SCHOOL_DEMO_MODE requires SCHOOL_ADMIN_KEY (it is shown publicly as the demo key)")


def write_allowed(method: str, path: str) -> bool:
    if method in ("GET", "HEAD", "OPTIONS"):
        return True
    return any(p.match(path) for p in _ALLOWED_WRITES)


async def read_only_guard(request: Request, call_next):
    if enabled() and not write_allowed(request.method, request.url.path):
        return JSONResponse({"detail": READ_ONLY_MESSAGE}, status_code=403)
    return await call_next(request)


def info() -> dict:
    if not enabled():
        return {"enabled": False}
    return {
        "enabled": True,
        "school_code": SCHOOL_CODE,
        "parent_username": PARENT_USERNAME,
        "parent_password": PARENT_PASSWORD,
        "admin_key": os.getenv("SCHOOL_ADMIN_KEY", ""),
        "sample_questions": SAMPLE_QUESTIONS,
        "read_only_message": READ_ONLY_MESSAGE,
    }


def escalation_reply() -> dict:
    """Chat response for an unanswered question; demo mode never stores visitor text."""
    return {
        "answer": ("I don't have verified information for that. In the full app, this question would now be "
                   "sent to school staff. This public demo doesn't store visitor questions; open the Staff "
                   "portal to see how sample questions are assigned and answered."),
        "source": None, "needs_staff": True, "retrieval": "no-confident-match",
        "escalation_id": None, "demo": True,
    }


def _now(offset_hours: float = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=offset_hours)).isoformat()


def seed(c, digest) -> None:
    """Load the fictional demo content once. Safe to call on every startup."""
    if c.execute("SELECT 1 FROM parent_accounts WHERE username=?", (PARENT_USERNAME,)).fetchone():
        return

    handbook = (DEMO_DOCS / "sunrise-valley-handbook.md").read_text(encoding="utf-8")
    fee_policy = (DEMO_DOCS / "fee-policy-2026.md").read_text(encoding="utf-8")

    c.execute("INSERT INTO documents(filename,title,content,uploaded_at,school_id) VALUES(?,?,?,?,1)",
              ("sunrise-valley-handbook.md", "Parent handbook 2026", handbook, _now(72)))
    c.execute("INSERT INTO knowledge(topic,answer,source,school_id) VALUES(?,?,?,1)",
              ("Sports day", "Sports day is on Friday 12 June 2026. Parents are welcome from 10 AM.",
               "Events calendar 2026"))

    # Approved fee policy that replaced the old "Fees" FAQ, with the resolved conflict on record.
    today = date.today().isoformat()
    policy_id = c.execute(
        """INSERT INTO policy_versions(policy_key,version,title,filename,content,effective_date,
           created_at,school_id,status,reviewed_at) VALUES(?,?,?,?,?,?,?,1,'approved',?) RETURNING id""",
        ("fees", 1, "Fee policy 2026", "fee-policy-2026.md", fee_policy, today, _now(48), _now(47))).fetchone()[0]
    fees_faq = c.execute("SELECT id FROM knowledge WHERE topic='Fees' AND school_id=1").fetchone()
    if fees_faq:
        c.execute("UPDATE knowledge SET active=FALSE WHERE id=?", (fees_faq[0],))
        c.execute("""INSERT INTO knowledge_conflicts(policy_id,legacy_type,legacy_id,status,resolved_at)
                     VALUES(?,'faq',?,'resolved',CURRENT_TIMESTAMP) ON CONFLICT DO NOTHING""",
                  (policy_id, fees_faq[0]))

    # A draft waiting for review, so the policy workflow has something to show.
    c.execute(
        """INSERT INTO policy_versions(policy_key,version,title,filename,content,effective_date,
           created_at,school_id,status) VALUES(?,?,?,?,?,?,?,1,'draft')""",
        ("late-pickup", 1, "Late pickup policy 2027", "late-pickup-policy-2027.md",
         "Sunrise Valley School - Late Pickup Policy 2027 (Demo). Children not collected by 4:00 PM wait "
         "in the library with a member of staff. Parents should phone the office if they will be late. "
         "Fictional sample for the Parent Assistant demo.",
         (date.today() + timedelta(days=45)).isoformat(), _now(5)))

    salt = secrets.token_hex(16)
    parent_id = c.execute(
        "INSERT INTO parent_accounts(username,display_name,salt,password_hash,school_id) "
        "VALUES(?,?,?,?,1) RETURNING id",
        (PARENT_USERNAME, PARENT_DISPLAY_NAME, salt, digest(PARENT_PASSWORD, salt))).fetchone()[0]

    questions = [
        ("Can my son bring his pet rabbit to show and tell next week?", "resolved", "Ms. Rao",
         "Yes, small pets may visit for show and tell on Friday afternoons with the class teacher's agreement.", 30),
        ("Is there a school trip planned for next term?", "assigned", "Mr. Iyer", None, 8),
        ("Can the school bus stop closer to Lakeview Apartments?", "open", None, None, 2),
    ]
    for text, status, assignee, reply, hours_ago in questions:
        created = _now(hours_ago)
        c.execute(
            """INSERT INTO escalations(question,status,created_at,school_id,assigned_to,resolution,
               updated_at,resolved_at,parent_id) VALUES(?,?,?,1,?,?,?,?,?)""",
            (text, status, created, assignee, reply, created if status != "open" else None,
             created if status == "resolved" else None, parent_id))
