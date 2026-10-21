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
untracked schemas are refused; the older bootstrap and SQLite migration tools
still produce untracked schemas and need a separately reviewed adoption plan.
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
The tests use SET ROLE on a disposable administrative connection to exercise
PostgreSQL's effective privilege checks, not real credential provisioning.
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

- Real runtime-login authentication and permission review in staging.
- Full HTTP workflow suite under the restricted login, including concurrent writes.
- Adoption path for existing bootstrap/SQLite-migrated databases.
- Restored-database application startup without patched readiness checks.
- Successful-release rollback drill and measured recovery objectives.
