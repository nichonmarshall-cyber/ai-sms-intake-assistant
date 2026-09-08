"""Retention sweep for user_sessions and login_attempts.

Login already runs this opportunistically, so a scheduler is optional. Run it
manually or from a cron job if you prefer deterministic cleanup:

    py scripts/purge_auth_tables.py
"""

from __future__ import annotations

from modules.auth.sessions import purge_expired
from modules.db import session_scope


def main() -> int:
    db = session_scope()
    try:
        result = purge_expired(db)
    finally:
        db.close()
    for key, count in result.items():
        print(f"{key}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
