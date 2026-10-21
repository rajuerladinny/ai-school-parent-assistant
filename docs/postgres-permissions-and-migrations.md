# PostgreSQL permissions and migration acceptance

Production activation remains blocked. These tools prepare and test the database
boundary; they do not enable the application production runtime.

## Separate migration and runtime identities

Use a dedicated migration identity that owns the application schema and can
create permission groups. Keep its DSN out of application worker configuration.
The scripts read `SCHOOL_POSTGRES_ADMIN_DSN` from the environment so credentials
need not be placed in command arguments. Supply it through the chosen secrets
manager; do not commit it or paste it into a review.

For a fresh, empty database, run from the repository root:

```text
python -m scripts.postgres_migrations
python -m scripts.postgres_runtime_role --role school_runtime
```

The migration runner applies numbered SQL files in order under one transaction
and advisory lock. A ledger records filenames, versions, checksums and timestamps.
Repeat execution does nothing. Changed, missing or reordered applied migrations
fail closed. A failed migration rolls back both DDL and ledger updates. Existing
untracked schemas are refused by the normal runner. The older bootstrap and
SQLite migration tools produce untracked schemas; adopt those explicitly using
the procedure below before running upgrades.
Keep applied SQL files immutable; add a new numbered file for subsequent changes.

The permission tool creates a fresh NOLOGIN group. It grants schema USAGE,
CRUD on the twelve application tables and USAGE on their owned sequences.
It grants no migration-ledger access, ownership, schema CREATE, TRUNCATE,
trigger modification or role administration. It refuses existing role names and
public schema configurations that implicitly grant CREATE to the new group.
It does not silently revoke existing grants. Review and correct such grants as
a separate administrative action, then rerun provisioning.

The deployment owner must separately create a restricted login, assign only
this permission group and verify its effective privileges. Do not give that
login membership in the owner, migration or administrative roles. The application
DSN must authenticate as this login; the migration DSN must never be substituted.
The permission-denial tests use SET ROLE to check effective privileges. The
HTTP acceptance suite additionally connects as a temporary restricted LOGIN,
asserts both current_user and session_user match that login, and exercises
parent/staff authentication, content, policy review, notifications, staff
workflows and tenant isolation. CI's PostgreSQL service uses password
authentication; the local disposable cluster uses loopback-only trust auth.
The permission group is database-wide and is not a substitute for application
tenant authorization. PostgreSQL PUBLIC privileges are additive; deployments
must also review inherited privileges and executable functions. See the official
[privilege rules](https://www.postgresql.org/docs/16/ddl-priv.html).

## Rollback acceptance

Tests demonstrate automatic rollback of a failed fresh migration and a failed
upgrade without losing the previous ledger or schema. They do not demonstrate
a downgrade after a successful incompatible migration.

For that release rollback, retain the previous application artifact and a
verified pre-change backup. Restore into a separate disposable database using
the existing restore-verification tools, verify schema, data and runtime
permissions, then test the previous application against it before switching
traffic. Logical backups use no-owner/no-ACL restoration, so runtime permission
groups and login memberships require explicit reprovisioning after restoration.
Do not run a destructive down migration to satisfy an acceptance checkbox.
Staging must still measure recovery time and data loss, verify connection and
traffic switching, and record the exact backup and application versions.

## Remaining acceptance

- Runtime-login credentials and effective permission review in staging.
- Restored-database application startup without patched readiness checks.
- Successful-release rollback drill and measured recovery objectives.

The versioned restore drill uses a separate empty database and real pg_dump /
pg_restore. It checks application values, sequence state and migration history,
then confirms the restored migration runner is a no-op. It reprovisions a
restricted login and verifies reads, writes and denied ledger access. Restore
comparison now rejects missing or altered ledger rows, including timestamps.
This validates database recovery; it does not bypass the application startup gate.

Concurrent policy-upload tests run with both owner and restricted-login DSNs,
covering both legacy and school-admin routes and a mix of those routes, with
and without previous versions. A separate owner connection holds the school row
lock; the monitor requires two waiting requests authenticated as the runtime
login before releasing it. Both uploads must then return distinct consecutive
versions while leaving the other school's policy unchanged. Administrative
monitoring and test data setup use the owner DSN; HTTP requests use the selected
runtime DSN. Production startup checks remain patched only within these tests.

## Adopt an existing untracked PostgreSQL database

Take and verify a backup first. Stop application writers and administrative DDL
for the maintenance window, then use the schema owner DSN:

```text
python -m scripts.postgres_migrations --adopt-existing
python -m scripts.postgres_migrations
```

Adoption supports only the reviewed 001+002 baseline, including databases
populated through the SQLite migration tool. It takes the migration advisory
lock and exclusive table locks with a five-second lock timeout. On the same
connection it builds a temporary reference schema from the checked-in SQL and
compares table/column definitions, constraints, indexes, trigger definitions and
enabled state, function definitions, owned sequence definitions, row-security
policies and extra types. Unknown or altered objects fail closed. Resolve drift
through a reviewed migration; do not alter the checker to bypass a mismatch.
Other schemas, grants, ownership and operational credentials require separate
review; this structural check does not certify existing record quality.

Only after comparison succeeds does adoption create the ledger and record the
baseline checksums. It never replays baseline SQL on application tables or
changes their records or sequence counters. The reference schema is removed,
and all changes roll back on failure. Existing ledgers are refused; subsequent
commands must use the normal runner. Tests cover bootstrap and populated
SQLite-migrated databases, preserving every application value and sequence state.
Keep other administrators from changing functions or creating objects during
adoption; table locks do not prevent all independent DDL.
