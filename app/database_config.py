"""Explicit database backend selection with fail-closed PostgreSQL readiness.

This module intentionally refuses to activate PostgreSQL until all runtime
queries, schema assumptions and data migration checks have been converted.
"""
import os
from urllib.parse import urlparse


def backend():
    selected=os.getenv("SCHOOL_DATABASE_BACKEND","sqlite").lower().strip()
    if selected not in ("sqlite","postgres"):
        raise RuntimeError("SCHOOL_DATABASE_BACKEND must be sqlite or postgres")
    return selected


def validate_configuration():
    selected=backend()
    if selected=="postgres":
        dsn=os.getenv("SCHOOL_POSTGRES_DSN","")
        parsed=urlparse(dsn)
        if parsed.scheme not in ("postgresql","postgres") or not parsed.hostname or not parsed.path.strip("/"):
            raise RuntimeError("SCHOOL_POSTGRES_DSN must be a PostgreSQL database URL")
        if os.getenv("SCHOOL_POSTGRES_RUNTIME_READY")!="1":
            raise RuntimeError("PostgreSQL runtime is not enabled until query and migration integration is verified")
        # Do not permit a manual environment flag to bypass the incomplete runtime adapter.
        raise RuntimeError("PostgreSQL runtime adapter integration is not complete")
    if os.getenv("SCHOOL_ENV")=="production":
        raise RuntimeError("SQLite is not approved for production")
    return "sqlite"
