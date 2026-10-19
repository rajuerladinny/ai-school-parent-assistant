# Production validation and release runbook

**Status: NOT APPROVED. Do not deploy with real parent, child, or school data.**

This runbook groups the remaining release work into one acceptance exercise. Passing local pytest (developer reported 119 passed, 2 warnings on 2026-10-19) is not equivalent to production acceptance.

## 1. Release boundary

- Preserve the fail-closed production database configuration. Both SQLite production use and the incomplete PostgreSQL runtime adapter are rejected by `app/database_config.py`.
- Keep optional ChromaDB vector retrieval disabled in production. Five known vulnerability findings were reported against locally installed ChromaDB 1.5.9. Do not treat the RAG gate as a dependency fix.
- Never bypass required branch review, disable branch protection, or deploy as part of merging.
- Store credentials in a secrets manager; never paste database URLs, bearer tokens, or password-bearing pytest `--showlocals` logs into tickets or Git.

## 2. One-pass engineering verification (local, disposable data)

Run from the repository root in a properly configured development environment:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --tb=short --disable-warnings
.\.venv\Scripts\python.exe -m pip_audit
```

For an isolated dependency assessment, separately audit the optional RAG requirements; report all findings and their fixed-version availability. Record command, environment, package versions, timestamp, and redacted result. Do not suppress findings to pass a release gate.

## 3. PostgreSQL runtime acceptance (BLOCKED)

- Inventory all application SQL calls and SQLite-specific schema/setup paths; convert to PostgreSQL-safe migrations with version tracking and reversible migration strategy.
- Run all HTTP endpoints and background tasks against disposable PostgreSQL without monkeypatching `database_config.validate_configuration`. Current integration tests override that check; they are **not** proof that production startup is ready.
- Exercise tenant isolation for parents, staff, school admins, notifications, escalations, documents, policies, and RAG.
- Prove transactional rollback, connection loss recovery, least-privilege application DB role, migration downgrade and clean startup from restored backup.
- Only after those pass, obtain explicit review to remove the PostgreSQL runtime rejection. Do not use `SCHOOL_POSTGRES_RUNTIME_READY=1` as a bypass.

## 4. Authentication and ingress acceptance (BLOCKED)

- Decide on managed identity and administrator MFA, password reset, account recovery, session expiry/revocation, and break-glass process.
- Test account disablement and school deactivation; verify existing parent/staff sessions cannot access any tenant data.
- Test Redis rate limiting across at least two separate app workers with shared authenticated TLS Redis; verify fail-closed behavior on Redis outage and recovery.
- Configure trusted reverse proxy, correct client-IP attribution, HTTPS redirect, explicit allowed hosts, certificate renewal, and HSTS at the edge. Test spoofed forwarding headers from untrusted clients.
- Review every privileged write route and ensure shared legacy admin-key endpoints remain inaccessible in production.

## 5. Operations and recovery acceptance (BLOCKED)

- Ship redacted structured logs to a central collector; validate that credentials, message contents and query strings are not logged.
- Establish error-rate, latency, auth throttle, database, queue and RAG-health alerting with a tested destination, on-call owner and escalation path.
- Run an isolated encrypted pg_dump/pg_restore exercise; compare counts, representative rows and tenant access controls. Record elapsed recovery time, measured data-loss window, retention and approved RPO/RTO.
- Perform a staging rollback rehearsal with representative synthetic traffic and confirm rollback does not violate schema compatibility.
- Obtain privacy/security reviews and named operational/release-owner go/no-go approval.

## 6. Merge and deploy decision

- PR #29 is ready for review but GitHub branch protection requires an approval from a reviewer with write access. No approving review was present at last check.
- A passing local test suite is developer-reported evidence only; GitHub status checks were not reported at the latest commit, and Actions budget was exhausted.
- Merge only after GitHub review requirements are met and the user requests it. **Merge is not deployment approval.**
- Deploy only when every applicable acceptance gate has independently verified evidence and the release owner explicitly authorizes deployment.
