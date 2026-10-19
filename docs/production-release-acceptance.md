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

## Database fail-closed regression gate

Automated tests in `tests/test_database_release_gate.py` require rejection of SQLite production mode, invalid PostgreSQL URLs, and a manual `SCHOOL_POSTGRES_RUNTIME_READY=1` override while the runtime adapter is incomplete. A passing schema integration workflow **does not** authorize a production launch. Before removing this gate, demonstrate runtime query compatibility, school isolation, migrations, backup/restore, rollback, and production-like end-to-end tests. Record explicit approval before deployment.

## Local verification evidence — 2026-10-19 (Windows, PostgreSQL 16.15, Memurai)

The following are **developer-reported local test results**, not CI or independent production acceptance. No real school records or public deployment were used.

| Verification | Observed result | Limitation |
| --- | --- | --- |
| Full pytest suite after login input validation | 109 passed, 2 skipped, 3 warnings | Two optional ChromaDB tests not run; deprecation warnings remain |
| Full PostgreSQL test suite repeatability (before latest auth changes) | 99 passed twice, 2 skipped | Disposable PostgreSQL 16 test databases, not a production workload |
| Targeted migration/restore, operational alert and authentication observability tests | 4 passed, 2 warnings | Does not verify encrypted backups, RPO/RTO or external alert delivery |
| Redis-compatible local Memurai connection | PING returned True | Loopback only, no production TLS or authenticated Redis configuration |
| Live Redis-backed parent account throttle | Attempts 1–5 allowed; attempt 6 returned HTTP 429 | One local Python process; cross-worker load untested |
| Live Redis-backed staff source-IP throttle | Attempts 1–30 allowed; attempt 31 returned HTTP 429 | Isolated synthetic IP; trusted-proxy behavior untested |
| Redis unavailable (unused loopback port) | HTTP 503, fail-closed | Does not replace network failure drills in staging |
| Local Gitleaks history scan | No leaks found in scanned 345 commits | GitHub alerts and all reachable refs not independently verified |
| pip-audit of installed environment | No known vulnerabilities reported | Optional RAG dependencies and clean locked dependency resolution not verified |

### Outstanding acceptance blockers

- **Production runtime:** PostgreSQL adapter activation remains explicitly blocked; SQLite production is also blocked. Do not bypass these checks.
- **Identity:** Managed identity provider, administrator MFA, password recovery, privileged authorization review, and end-to-end tenant isolation still require implementation and acceptance.
- **Ingress and Redis:** Trusted-proxy/IP handling, production HTTPS/TLS termination, Redis TLS/authentication and multi-worker throttling still need staging evidence.
- **Operations:** Centralized logs, rolling-window fleet metrics, tested alerts/on-call, privacy review, encrypted backup retention and RPO/RTO remain unverified.
- **Repository:** Branch protection enforcement, GitHub secret-scanning alerts, optional RAG audit, ChromaDB integration, and full Apache-2.0 license text remain outstanding.
- **Release:** No deployment, PR merge, or production approval is implied by local test success.
