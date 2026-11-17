# Project Overview — AI School Parent Communication Assistant

A short map of the codebase. For setup details, feature notes and current limitations, see [README.md](README.md).

> **Status:** Development prototype. Use fictional school data only (demo school: *Sunrise Valley School*, school code `demo`). Not approved for production deployment.

## What it is

A FastAPI web app that helps parents get answers grounded in approved school content, and gives school staff a place to handle what the assistant can't answer.

- **Parents** ask questions in a chat, see the source of each answer, track their escalated questions, and receive in-app policy update notifications.
- **Staff** review and respond to escalated parent questions.
- **School admins** manage FAQs, documents and versioned policies, and resolve knowledge conflicts before approving policies.

## Tech stack

| Layer | Technology |
|---|---|
| Web API | Python 3.10+, FastAPI, Uvicorn |
| UI | Single page served from `app/index.html` |
| Storage | SQLite (runnable today); PostgreSQL schema, migration and restore tooling (under validation, runtime not yet enabled) |
| Retrieval (optional) | ChromaDB + Sentence Transformers, with keyword FAQ fallback |
| Answer generation (optional) | Local model via Ollama; otherwise returns retrieved excerpts |
| Login throttling | Redis (fails closed when unavailable) |
| Tests / CI | pytest, GitHub Actions (manually triggered) |

## Directory layout

```
ai-school-parent-assistant/
├── app/                  # FastAPI application
├── migrations/postgresql # SQL migrations for the PostgreSQL schema
├── scripts/              # Offline admin, migration, restore and audit tools
├── tests/                # pytest suite
├── docs/                 # Release, security and operations runbooks
├── .github/workflows/    # CI, PostgreSQL schema and vector integration jobs
├── requirements.txt      # Core dependencies
└── requirements-rag.txt  # Optional local RAG dependencies
```

## Application modules (`app/`)

| Module | Responsibility |
|---|---|
| `main.py` | App setup, SQLite schema, chat, FAQ/knowledge and document endpoints; mounts all routers |
| `rag.py` | Optional vector retrieval (ChromaDB + Sentence Transformers) scoped per school |
| `policies.py` | Versioned policies with explicit approval and effective dates |
| `conflicts.py` | Flags topic overlaps that block policy approval until resolved |
| `notifications.py` | Opt-in in-app policy update inbox (no email/SMS) |
| `auth.py` | School-managed parent accounts, scrypt hashing, expiring sessions (`/api/auth`) |
| `parent_questions.py` | Parents track their own escalated questions |
| `staff.py` | Escalation workflow for unanswered questions |
| `staff_auth.py` | School-scoped staff/admin accounts with bearer sessions |
| `school_admin.py` | School-scoped knowledge admin using authenticated admin sessions |
| `shared_login_limit.py` | Atomic, Redis-backed login throttling across workers |
| `observability.py` | Privacy-conscious request metrics |
| `database_config.py` | Backend selection; rejects PostgreSQL until runtime conversion is complete |
| `postgres_adapter.py` | Incremental psycopg compatibility layer (not yet wired into the app) |

## Scripts (`scripts/`)

| Script | Purpose |
|---|---|
| `postgres_bootstrap.py` | Initialize an empty PostgreSQL schema or validate an existing one |
| `bootstrap_school_admin.py` | Interactively create the first admin for an existing school |
| `migrate_sqlite_to_postgres.py` | Offline, transactional SQLite → PostgreSQL data transfer |
| `verify_postgres_restore.py` / `postgres_restore_verify.py` | Backup/restore drill into a disposable database |
| `postgres_data_integrity.py` | Compare values and sequence state after a restore |
| `audit_sqlite_sql.py` | List SQLite-only SQL still blocking a PostgreSQL runtime |
| `smoke_rag.py` | Real local embedding smoke test |

## Quick start

```bash
python -m venv .venv
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Set `SCHOOL_ADMIN_KEY` to a long random secret before starting, then open http://127.0.0.1:8000. For vector search, also install `requirements-rag.txt`.

Run the tests:

```bash
pytest
```

## Key configuration

| Variable | Purpose |
|---|---|
| `SCHOOL_ADMIN_KEY` | Legacy shared admin key (demo only) |
| `SCHOOL_DATABASE_BACKEND` | `sqlite` is the only runnable backend today |
| `RAG_VECTOR_PATH` | Chroma data directory (default `./chroma_data`) |
| `RAG_EMBEDDING_MODEL` | Sentence Transformers model name |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | Optional local answer generation |

## Further documentation

- [docs/demo/DEMO_GUIDE.md](docs/demo/DEMO_GUIDE.md): step-by-step demo with demo credentials and sample files
- [README.md](README.md): full feature notes and limitations
- [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md)
- [docs/PRODUCTION_READINESS_ACCEPTANCE.md](docs/PRODUCTION_READINESS_ACCEPTANCE.md)
- [docs/PUBLIC_RELEASE_SECURITY_CHECKLIST.md](docs/PUBLIC_RELEASE_SECURITY_CHECKLIST.md)
- [docs/production-validation-runbook.md](docs/production-validation-runbook.md)
- [docs/security-operations-runbook.md](docs/security-operations-runbook.md)

## License

Apache License 2.0. See [LICENSE](LICENSE).
