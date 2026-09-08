"""Create the first platform administrator.

Chicken-and-egg fix: /api/admin/users requires an existing admin, so the very
first one has to be made out of band.

    py scripts/create_admin.py --email you@ntxautomationco.com

The password is read from a prompt, never from argv, so it does not land in
shell history or the process list.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from uuid import uuid4

from sqlalchemy import select

from modules.auth import passwords
from modules.db import session_scope
from modules.models import PlatformUser


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or promote an NTX platform admin.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument(
        "--role", default="admin", choices=["admin", "staff"], help="Platform role to grant."
    )
    args = parser.parse_args()

    email = args.email.strip().lower()
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")

    if password != confirm:
        print("Passwords do not match.", file=sys.stderr)
        return 1

    error = passwords.validate_password_strength(password)
    if error:
        print(error, file=sys.stderr)
        return 1

    db = session_scope()
    try:
        existing = db.execute(
            select(PlatformUser).where(PlatformUser.email == email)
        ).scalar_one_or_none()

        if existing is not None:
            existing.password_hash = passwords.hash_password(password)
            existing.platform_role = args.role
            existing.is_platform_admin = args.role == "admin"
            existing.is_active = True
            db.commit()
            print(f"Updated existing user {email} as platform {args.role}.")
            return 0

        user = PlatformUser(
            id=str(uuid4()),
            email=email,
            display_name=args.name or email.split("@")[0],
            password_hash=passwords.hash_password(password),
            platform_role=args.role,
            is_platform_admin=args.role == "admin",
            is_active=True,
        )
        db.add(user)
        db.commit()
        print(f"Created platform {args.role}: {email}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
