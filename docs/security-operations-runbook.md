# Security and operations runbook

**Deployment is blocked.** This is implementation guidance, not operational acceptance or authorization to deploy.

## Shared login throttling

Configure `SCHOOL_RATE_LIMIT_REDIS_URL` (a `rediss://` TLS Redis URL with authenticated access) and `SCHOOL_RATE_LIMIT_KEY_SECRET` (random secret of at least 32 characters) using a secrets manager. Redis must be private to application workloads. Plaintext `redis://` is refused by default; `SCHOOL_ALLOW_INSECURE_REDIS=1` is an explicit exception requiring documented security approval and isolated network transport. Parent and staff endpoints share the same Redis service and atomically limit account and source-IP requests over a five-minute window. Account thresholds are 5 and source-IP thresholds are 30. The account and IP limits are scoped by authentication realm. Counters are not cleared after successful login. Authentication fails closed if Redis is inaccessible. Do not trust arbitrary forwarded IP headers; configure trusted ingress proxies separately.

Test with at least two application workers and one shared Redis instance. Verify account thresholds across workers, IP thresholds across different usernames, simultaneous login bursts, retry-after responses, Redis outage behavior, and rate-limit metrics. Test with real Redis before accepting this gate.

## Authentication and identity

Demo credentials and the shared bootstrap administrator key are not an approved production identity solution. Select and integrate a managed identity provider with administrator MFA, reset/recovery, revocation and audit events. Review school deactivation, staff disablement, parent disablement, and tenant-scoped permissions. Existing sessions must not silently regain access after reactivation.

## Monitoring and alerts

Capture redacted structured request logs and server-generated request IDs in centralized collection. Never log passwords, bearer tokens, authorization headers, query strings or parent messages. Configure dashboards and alerts for sustained 5xx errors, p95 latency, elevated 401/429/503 rates, Redis health, database connectivity, queue backlog and retrieval errors. Set thresholds based on staging baselines, assign named on-call owners and test notification delivery. Local counters alone are insufficient for production.

## Deployment and rollback

Enforce HTTPS at the trusted edge and explicitly configure allowed hosts. Use least-privilege secrets and short-lived deployment credentials. Verify schema migrations in a disposable PostgreSQL environment, test backward compatibility, stage a canary, and practice rollback. The current PostgreSQL runtime remains deliberately blocked; never bypass it with an environment flag. Do not deploy real school data until runtime integration and security review are complete.

## Backup and restore acceptance

Run encrypted `pg_dump` to a protected location, restore with `pg_restore` into an isolated environment, and compare schema, row counts, representative records and access restrictions. Record timestamps, RPO/RTO, encryption and retention controls, incident contacts, privacy review, and approval signatures. No checkboxes may be marked passed without test evidence.

## Go/no-go

Security owner, operational owner, privacy owner and release owner must sign off independently. Passing CI does not authorize merging or deployment.

## Authentication monitoring and alert evaluation

Structured `auth_rate_limit` events include only a bounded realm (`parent` or `staff`) and outcome (`allowed`, `throttled`, `unavailable`). They contain no account identifier, IP, credentials, or request body.

The `observability.alert_candidates()` helper uses **cumulative counters**, not a rolling time window. It identifies candidate alerts at 10 throttled events per realm or 1 Redis-unavailable event per realm. These thresholds are starting points for tests, **not production alert rules**. Configure the log aggregation platform to evaluate equivalent fleet-wide metrics over a defined 5-minute rolling window, with ownership, notification routing, deduplication, and a tested escalation path. In-memory counters reset on process restart and cannot represent multi-worker totals.

Operational acceptance remains blocked until a real centralized collector, alert delivery, dashboard, and alert drill are demonstrated.
