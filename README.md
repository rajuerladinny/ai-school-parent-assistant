# AI School Parent Communication Assistant

Standalone **fictional-school MVP** featuring a parent chat and a school administration dashboard.

## Fictional sample school
Sunrise Valley School. All initial facts are illustrative and must not be treated as a real school's policies.

## Features
- Parents can ask about school timings, holidays, fees, admissions and events.
- Responses are based on school-approved knowledge entries and include source labels.
- Admin can add/delete approved information with a configured secret key.
- Unknown questions enter a staff review queue.
- SQLite storage and automated backend tests.

**Important:** This is a **keyword-matching FAQ prototype**, not an LLM-powered autonomous AI agent. Ambiguous queries may match the wrong FAQ. Do not use with real children's personal data.

## Run locally
Requires Python 3.10+.

```bash
python -m venv .venv
# Activate your environment for your operating system
pip install -r requirements.txt
# Configure SCHOOL_ADMIN_KEY with a long random secret
uvicorn app.main:app --reload
```

Visit http://127.0.0.1:8000 for the parent chat and admin dashboard.

Run tests:

```bash
python -m pytest -q
```

## Safety and privacy
**Do not deploy this demo publicly.** There is no parent verification, staff login system, rate limiting, audit logging, multi-school isolation, or secure student-data workflow. Avoid entering sensitive personal data. For real school use, add verified document ingestion, robust authentication, retention and deletion controls, stronger retrieval and a security/privacy review.

## Roadmap
1. Approved document uploads, citations and reliable AI retrieval.
2. Staff login, review and approval workflow.
3. English/Kannada multilingual parent chat; opt-in WhatsApp integration.
4. Secure parent accounts and carefully scoped student-specific features.
5. School pilots and production hardening.
