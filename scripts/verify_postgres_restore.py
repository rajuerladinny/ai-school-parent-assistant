"""Verify a PostgreSQL logical backup by restoring into a disposable database.

Requires PostgreSQL client binaries, a running server and credentials. Never restores
into the source database. Run against an isolated test cluster, not production.
"""
import argparse

if __name__ == "__main__" and not __package__:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.postgres_restore_verify import verify as verify_restore


def verify(source_dsn,restore_dsn):
    if not source_dsn:
        raise ValueError("Source database DSN is required")
    if source_dsn==restore_dsn:
        raise ValueError("Source and restore database DSNs must differ")
    if not restore_dsn:
        raise ValueError("Disposable restore database DSN is required")
    verify_restore(source_dsn, restore_dsn)
    return True


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dsn",required=True)
    parser.add_argument("--restore-dsn",required=True,
                        help="MUST point to a separate, empty disposable database")
    args=parser.parse_args()
    verify(args.source_dsn,args.restore_dsn)
    print("Backup and restore data and sequence verification passed")
