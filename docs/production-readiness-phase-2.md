# Production readiness — phase 2 (PR #30)

**Release status: BLOCKED. No deployment or merge approval is implied.**

## Implementation workstreams

1. **PostgreSQL runtime:** Inventory SQLite-only SQL and schema assumptions; implement PostgreSQL-safe runtime queries, versioned migrations, tenant-scoped data access, downgrade and rollback. Preserve the current fail-closed production startup gate until integration tests pass without monkeypatching it.
2. **Authentication:** Select managed identity, enforce admin MFA, session revocation and recovery; test disabled schools, staff and parents; audit legacy privileged endpoints and cross-school authorization.
3. **Dependency security:** Remediate or replace the optional ChromaDB version with five locally reported advisories; keep production RAG disabled until audited and explicitly accepted.
4. **Network and rate limiting:** Verify trusted reverse proxy and HTTPS, explicit host allowlist, authenticated TLS Redis and shared throttling across multiple workers, plus Redis outage/recovery.
5. **Monitoring and recovery:** Configure centralized redacted logs, actionable alerts, encrypted backup retention, measured RPO/RTO and PostgreSQL restore plus staging rollback drills.
6. **Release evidence:** Run local tests, security audits, staging tests and independent reviews; document sign-off and maintain separate merge/deploy approval.

## Acceptance rules

- No real school, child or parent records in development or test environments.
- No production database gate removal solely because a developer sets an environment variable.
- No suppression of vulnerability findings to satisfy the checklist.
- No automatic GitHub Actions trigger while Actions minutes are exhausted; commits on this branch use [skip ci].
- Merging PR #30 does not authorize deployment.

## Initial baseline

- PR #29 merged to main on 2026-10-19.
- Developer-reported local suite: 120 passed, 2 warnings, 0 failures, before this PR.
- PostgreSQL production runtime remains blocked intentionally.
- External infrastructure acceptance is not yet demonstrated.
