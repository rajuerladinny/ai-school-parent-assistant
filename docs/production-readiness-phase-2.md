# Production readiness - consolidated draft PR #30

Release status: BLOCKED. Merging this PR does not authorize deployment.

This draft collects the remaining work in one PR, with separate commits for review.
PRs #31 through #36 are already merged into main; their database, authentication,
policy concurrency, restore integrity and tenant indexing fixes are prerequisites.

## Acceptance checklist

| Workstream | Evidence already available | Remaining acceptance |
| --- | --- | --- |
| PostgreSQL | Isolated schema, adapter, HTTP and restore tests; restricted-login workflows and concurrent writes; checksum migrations, drift-checked existing-schema adoption, failed-upgrade rollback and versioned restore | Successful-release rollback, startup against restored database without patched release gates |
| Connection recovery | Real backend termination test verifies transaction rollback and a successful fresh connection | Staging outage and recovery under concurrent traffic |
| Identity | Tenant-scoped login, disabled-account/session checks, school-code login | Choose managed provider, admin MFA, recovery and role lifecycle, audited break-glass procedure |
| Network | Production import and request checks reject plaintext Redis even with the legacy override | Trusted proxy/client-IP configuration, authenticated TLS Redis across multiple workers, outage drill |
| Retrieval | Real isolated vector store tests cover tenant and policy eligibility | Fresh optional dependency audit and remediation, representative model answer-quality evaluation |
| Operations | Redacted application events and isolated restore tools | Central collection and alerts, encrypted backup retention, measured RPO/RTO, health monitoring |
| Release | Main baseline: 170 local tests passed before this draft update | Synthetic staging load, rollback drill, privacy/security review and named operational sign-off |

## Rules for recording evidence

- Use fictional records and disposable databases for automated acceptance.
- Keep production database and retrieval startup gates intact until their acceptance criteria are met.
- Record exact commit, command, result and environment for each drill; do not treat a skipped test as acceptance.
- CI must run on the consolidated branch; old Actions-budget and skip-CI instructions no longer apply.
- Provider and staging-platform choices are pending. Provider-neutral preparation may continue, but external deployment evidence cannot be inferred from local tests.
- Keep this PR draft until implementation and evidence are complete. Merge and deployment remain separate decisions.

## Current batch

The database follow-up adds restricted runtime permission provisioning and a
transactional checksum migration runner. See
[permissions and migration acceptance](postgres-permissions-and-migrations.md)
for commands, boundaries and remaining staging acceptance.

- Synchronize the existing draft with main through PR #36.
- Reject the insecure Redis override consistently at production startup and login.
- Exercise a real PostgreSQL connection termination, uncommitted-write rollback,
  and successful fresh-connection write/read, using the disposable test fixture.

## Provider-neutral identity contract

The selected provider must supply a verified issuer and audience, an immutable
subject identifier, and a documented admin MFA assurance claim. Account linking
must use an explicit reviewed mapping to the existing school-scoped account;
email or a caller-supplied school ID alone must never grant membership.
Application authorization remains server-side and scoped to school and role.

Before enabling an integration, test invalid signatures, wrong issuer/audience,
expired tokens, key rotation, missing MFA, disabled memberships, session
revocation, recovery and cross-school access. Provider configuration, callbacks,
secrets and logout/revocation behavior will be implemented after selection.
No new identity-provider tokens are accepted by the current application.

## Local verification for this batch

At implementation commit 595db964d648b30676dd0ec2d20bfb56a09be3cb,
`python -m pytest -q -o faulthandler_timeout=90` passed 173 tests with
2 existing FastAPI startup-event deprecation warnings. Environment: Windows,
Python 3.13, disposable PostgreSQL 16 cluster, offline local vector dependencies.
This is local acceptance evidence, not a staging or deployment sign-off.
