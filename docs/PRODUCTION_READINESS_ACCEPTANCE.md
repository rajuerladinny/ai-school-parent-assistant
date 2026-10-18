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
