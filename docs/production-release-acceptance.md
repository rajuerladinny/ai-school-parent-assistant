# Production release acceptance checklist (draft)

**Status: BLOCKED — do not deploy with real school or parent data.**

This checklist is a release gate, not evidence that any item has passed. CI passing is necessary but insufficient.

## Identity and tenant isolation
- [ ] Shared Redis atomic per-account and per-source-IP limiter implemented with unit tests. Still verify real Redis behavior across multiple worker instances, with retry and lockout tests.
- [ ] Decide on a managed identity provider, MFA for administrators, password reset, account recovery, session expiry and explicit session revocation.
- [ ] Verify disabled schools, parents and staff cannot log in or use existing sessions. Test cross-school data boundaries in API, SQL and RAG.
- [ ] Review authorization for all write endpoints; ensure legacy shared-admin-key endpoints cannot be used in production.

## Deployment and secrets
- [ ] Set SCHOOL_ENV=production; enforce HTTPS at the trusted edge and verify proxy-forwarded headers are accepted only from trusted proxies.
- [ ] Set explicit SCHOOL_ALLOWED_HOSTS and SCHOOL_ENFORCE_HTTPS=1; reject wildcard hosts.
- [ ] Store database credentials, admin keys and signing secrets in a secrets manager. Document rotation and emergency revocation.
- [ ] Replace SQLite with an approved PostgreSQL runtime. **Current app/database_config.py explicitly rejects PostgreSQL runtime activation even when SCHOOL_POSTGRES_RUNTIME_READY=1.** Do not override this gate until integration is complete.
- [ ] Confirm schema migrations, database least-privilege permissions and rollback compatibility using a disposable environment.
- [ ] Run a staging deployment with representative traffic and a documented rollback exercise.

## Observability and incident response
- [ ] Redacted structured HTTP logs with correlation IDs, status class and latency implemented. Validate centralized collection and never log bearer tokens, passwords or parent messages by default.
- [ ] Monitor error rate, request latency, authentication throttling, database connection health, RAG failures and queue/backlog health.
- [ ] Configure alert destinations, escalation ownership, severity thresholds and a tested on-call response path.
- [ ] Record incident response, data retention and privacy review outcomes.

## Backup, restore and acceptance
- [ ] Perform an isolated pg_dump/pg_restore drill and verify source and restored security controls, row counts and representative record fidelity.
- [ ] Verify backup encryption, access controls, retention, recovery point objective (RPO) and recovery time objective (RTO).
- [ ] Record test evidence, security review, privacy review, operational owner approval and explicit go/no-go sign-off.
- [ ] Deploy only after all mandatory gates are complete and the release owner authorizes it.

**Pull request policy:** Keep this PR in draft until implementation and evidence satisfy the gates. Merging code is not production approval.
