# Production readiness completion — acceptance gate

This branch consolidates the remaining implementation milestones. **Do not deploy or onboard real schools until every item is implemented, independently tested, and reviewed.** PostgreSQL is intentionally disabled in the API until the gate is satisfied.

## Required implementation and verification

- [ ] PostgreSQL-backed FastAPI runtime, schema migrations, and application startup with explicit backend selection; no SQLite-only SQL or PRAGMA in PostgreSQL paths
- [ ] End-to-end API tests against PostgreSQL 16 for parent, staff, knowledge, documents, policies, notifications, escalations and questions
- [ ] Individual school administrator and staff authentication with role-specific authorization; remove production reliance on shared admin keys
- [ ] Tenant-scoped read and write paths, including ChromaDB school filtering and tests that attempt cross-school access
- [ ] Full SQLite-to-PostgreSQL migration for every application table, foreign keys, sequence resets, row counts, and representative data fidelity checks
- [ ] Migration failure/rollback and retry tests using an isolated PostgreSQL instance
- [ ] Automated backup plus actual restore into a disposable database, validated against source counts and sample data
- [ ] Security review: rate limits, secrets, TLS/hosts, account/session controls, uploads, dependency/secret scanning and authorization testing
- [ ] Operational documentation: deployment, migration, rollback, backup schedules, restore drill, monitoring and incident response

## Existing components to retain

- ChromaDB is optional for vector retrieval, not the authoritative store for structured school data.
- Existing PostgreSQL adapter, schema bootstrap, and recovery verification utilities are groundwork, not evidence of production readiness.
- Never switch production traffic or import real school data merely because this PR is opened or merged.

## Merge criteria

Every checkbox requires a linked implementation/test or verification evidence. A green unit-test workflow alone does not satisfy migration, restore or security acceptance.

## Verified implementation evidence (2026-10-18)

- [x] PostgreSQL 16 schema smoke tests and adapter transaction tests passed in GitHub Actions (PR #27, merged).
- [x] Staff login throttling and its unit test committed in PR #28; School Assistant CI run 235 passed.
- [x] PostgreSQL schema includes staff accounts/sessions and bootstrap validation; PostgreSQL Schema Integration run 101 passed.
- [x] Migration includes staff accounts/sessions, parent sessions, escalations/events and knowledge conflicts; source table/column validation tests passed in School Assistant CI run 239.
- [ ] **Not verified:** Full migrated dataset integrity, actual PostgreSQL-backed API, restore drill, security assessment, and cross-tenant authorization for every endpoint.

- [x] School-local assignee validation and protection against staff changing another staff member's assigned question committed; both School Assistant CI run 247 and PostgreSQL Schema Integration run 109 passed. These runs do not independently prove cross-tenant API behavior.

The completed subitems above do **not** satisfy the unchecked top-level release gates. Production readiness remains **BLOCKED**.

## CI evidence update — 2026-10-18

- [x] **Disposable PostgreSQL migration and recovery integration drill:** PostgreSQL Schema Integration [run 117](https://github.com/rajuerladinny/ai-school-parent-assistant/actions/runs/39144631187) passed on commit `2b0586219d413881c505a6848f0af8279e4b3219`. The test provisions disposable PostgreSQL databases, migrates SQLite data, verifies dry-run rollback and counts, then executes `pg_dump` and `pg_restore` and compares all application-table counts.
- [x] **Standard CI:** School Assistant CI [run 255](https://github.com/rajuerladinny/ai-school-parent-assistant/actions/runs/39144631253) passed on the same commit.
- [ ] **Production PostgreSQL runtime:** still intentionally blocked by `app/database_config.py`; no live PostgreSQL FastAPI endpoint tests.
- [ ] **Complete tenant authorization:** demo-school-only parent guard and shared admin-key endpoints remain.
- [ ] **Production recovery readiness:** disposable CI restore passed; no production-environment restore, RPO/RTO evidence, or operational signoff.
- [ ] **Security assessment:** no full endpoint authorization matrix or production penetration/security review.

Passing CI verifies the isolated drill, not production operational readiness.

## Priority 1, Step 2 — FastAPI connection routing (2026-10-18)

- [x] Implemented PostgreSQL selection in `app.main.db()`, using `app.postgres_adapter.connect` and `SCHOOL_POSTGRES_DSN`.
- [x] Added a PostgreSQL startup branch that validates an externally provisioned schema instead of running SQLite DDL or demo seeding.
- [x] Added tests for adapter routing, SQLite fallback and fail-closed PostgreSQL startup (`tests/test_postgres_fastapi_routing.py`).
- [ ] Awaiting CI evidence for these changes.
- [ ] PostgreSQL runtime activation remains deliberately blocked until API SQL compatibility, tenant isolation and real PostgreSQL FastAPI integration tests are verified. Do not remove the guard merely to enable production.
