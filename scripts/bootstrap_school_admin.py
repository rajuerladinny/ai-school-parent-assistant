"""Explicit, interactive bootstrap for the first administrator of an existing school.

Requires a separately initialized PostgreSQL database. Never runs at API startup.
Use an administrative database connection in a trusted terminal; do not pass
passwords as command-line arguments or store them in configuration files.
"""
import argparse
import getpass
import re
import secrets

def bootstrap(dsn, school_id, username, display_name, password):
    import psycopg
    from app.auth import digest
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{3,80}", username):
        raise ValueError("Invalid username")
    if not 2 <= len(display_name.strip()) <= 80:
        raise ValueError("Invalid display name")
    if not 12 <= len(password) <= 128:
        raise ValueError("Password must be 12 to 128 characters")
    salt = secrets.token_hex(16)
    with psycopg.connect(dsn) as conn:
        # Serialize concurrent bootstrap attempts for the same school.
        school = conn.execute(
            "SELECT id FROM schools WHERE id=%s AND active=TRUE FOR UPDATE",
            (school_id,)).fetchone()
        if not school:
            raise ValueError("Active school not found")
        if conn.execute(
            "SELECT 1 FROM staff_accounts WHERE school_id=%s AND role='school_admin' LIMIT 1",
            (school_id,)).fetchone():
            raise ValueError("School already has an administrator; bootstrap refused")
        row = conn.execute(
            "INSERT INTO staff_accounts(school_id,username,display_name,salt,password_hash,role) "
            "VALUES(%s,%s,%s,%s,%s,'school_admin') RETURNING id",
            (school_id,username.lower(),display_name.strip(),salt,digest(password,salt))).fetchone()
        return row[0]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn",required=True,help="PostgreSQL DSN; avoid embedded secrets")
    parser.add_argument("--school-id",type=int,required=True)
    parser.add_argument("--username",required=True)
    parser.add_argument("--display-name",required=True)
    args = parser.parse_args()
    password = getpass.getpass("New administrator password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        parser.error("Passwords do not match")
    account_id = bootstrap(args.dsn,args.school_id,args.username,args.display_name,password)
    print(f"Created initial school administrator account ID {account_id}")
