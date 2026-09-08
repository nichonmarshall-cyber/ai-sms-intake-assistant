"""Server-side, revocable dashboard sessions.

Design notes for future maintainers:

* The cookie carries an opaque random token. Postgres stores only its SHA-256,
  so a database disclosure cannot be replayed as a live login.
* Revocation is immediate because every request re-reads the row. That is one
  extra query per authenticated API call -- the deliberate cost of being able
  to kill a session for a departing client user.
* ``last_activity_at`` is refreshed at most once per ACTIVITY_REFRESH_SECONDS so
  ordinary dashboard use does not turn every GET into a write.
"""

from __future__ import annotations

import logging
import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session as DBSession

from modules.auth.crypto import hash_ip, hash_token, new_token, tokens_match
from modules.models import LoginAttempt, PlatformUser, UserSession

logger = logging.getLogger(__name__)


SESSION_COOKIE_NAME = "ntx_session"
CSRF_COOKIE_NAME = "ntx_csrf"

ABSOLUTE_LIFETIME = timedelta(days=7)
IDLE_TIMEOUT = timedelta(hours=12)
ACTIVITY_REFRESH_SECONDS = 300

LOGIN_ATTEMPT_RETENTION = timedelta(days=30)
REVOKED_SESSION_RETENTION = timedelta(days=30)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware_utc(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo on round-trip; Postgres keeps it. Normalize both."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class IssuedSession:
    session_token: str
    csrf_token: str
    row: UserSession


def create_session(
    db: DBSession,
    *,
    user_id: str,
    raw_ip: str | None = None,
    user_agent: str | None = None,
) -> IssuedSession:
    """Mints a new session and returns the raw tokens exactly once."""
    session_token = new_token()
    csrf_token = new_token()
    now = _utcnow()

    row = UserSession(
        user_id=user_id,
        token_hash=hash_token(session_token),
        csrf_hash=hash_token(csrf_token),
        created_at=now,
        last_activity_at=now,
        expires_at=now + ABSOLUTE_LIFETIME,
        ip_hash=hash_ip(raw_ip),
        user_agent=(user_agent or "")[:255] or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return IssuedSession(session_token=session_token, csrf_token=csrf_token, row=row)


def load_session(db: DBSession, session_token: str | None) -> tuple[UserSession, PlatformUser] | None:
    """Resolves a cookie token to a live session, or None.

    Returns None for: unknown token, revoked session, expired session, idle
    timeout, or a deactivated user. Revocation and expiry are checked before
    any activity bookkeeping so a killed session fails on the very next request.
    """
    if not session_token:
        return None

    token_hash = hash_token(session_token)
    row = db.execute(
        select(UserSession).where(UserSession.token_hash == token_hash)
    ).scalar_one_or_none()
    if row is None:
        return None

    now = _utcnow()
    if row.revoked_at is not None:
        return None
    if _as_aware_utc(row.expires_at) <= now:
        return None
    last_activity = _as_aware_utc(row.last_activity_at) or now
    if now - last_activity > IDLE_TIMEOUT:
        return None

    user = db.get(PlatformUser, row.user_id)
    if user is None or not user.is_active:
        return None

    return row, user


def touch_session(db: DBSession, row: UserSession) -> None:
    """Refreshes last activity, but only after a quiet interval has passed."""
    now = _utcnow()
    last_activity = _as_aware_utc(row.last_activity_at) or now
    if (now - last_activity).total_seconds() < ACTIVITY_REFRESH_SECONDS:
        return
    db.execute(
        update(UserSession).where(UserSession.id == row.id).values(last_activity_at=now)
    )
    db.commit()
    row.last_activity_at = now


def revoke_session(db: DBSession, row: UserSession) -> None:
    if row.revoked_at is not None:
        return
    now = _utcnow()
    db.execute(update(UserSession).where(UserSession.id == row.id).values(revoked_at=now))
    db.commit()
    row.revoked_at = now


def revoke_all_for_user(db: DBSession, user_id: str) -> int:
    """Used when an admin disables a user or a password changes."""
    result = db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=_utcnow())
    )
    db.commit()
    return int(result.rowcount or 0)


def verify_csrf(row: UserSession, presented_token: str | None) -> bool:
    """Constant-time check of a presented CSRF token against this session."""
    return tokens_match(presented_token or "", row.csrf_hash)


def purge_expired(db: DBSession) -> dict[str, int]:
    """Retention sweep so the auth tables cannot grow without bound."""
    now = _utcnow()
    sessions_removed = db.execute(
        delete(UserSession).where(UserSession.expires_at < now - REVOKED_SESSION_RETENTION)
    ).rowcount
    revoked_removed = db.execute(
        delete(UserSession).where(
            UserSession.revoked_at.is_not(None),
            UserSession.revoked_at < now - REVOKED_SESSION_RETENTION,
        )
    ).rowcount
    attempts_removed = db.execute(
        delete(LoginAttempt).where(LoginAttempt.created_at < now - LOGIN_ATTEMPT_RETENTION)
    ).rowcount
    db.commit()
    return {
        "expired_sessions": int(sessions_removed or 0),
        "revoked_sessions": int(revoked_removed or 0),
        "login_attempts": int(attempts_removed or 0),
    }


def maybe_purge(db: DBSession, probability: float = 0.02) -> None:
    """Opportunistic sweep on login. Cheap, and needs no scheduler on Render."""
    if random.random() >= probability:
        return
    try:
        purge_expired(db)
    except Exception:
        logger.exception("[auth] Retention sweep failed; continuing.")
        db.rollback()


def cookie_secure() -> bool:
    """Secure is on unless a developer explicitly opts out for local HTTP."""
    explicit = os.getenv("SESSION_COOKIE_SECURE", "").strip().lower()
    if explicit in {"1", "true", "yes", "on"}:
        return True
    if explicit in {"0", "false", "no", "off"}:
        return False
    return os.getenv("FLASK_ENV", "development").strip().lower() == "production"


COOKIE_PATH = "/"


def cookie_kwargs(*, http_only: bool) -> dict:
    """Shared cookie attributes. Deletion must reuse these exact values."""
    return {
        "path": COOKIE_PATH,
        "secure": cookie_secure(),
        "httponly": http_only,
        "samesite": "Lax",
    }


def set_auth_cookies(response, issued: IssuedSession) -> None:
    max_age = int(ABSOLUTE_LIFETIME.total_seconds())
    # Session token: HttpOnly, never readable by JavaScript.
    response.set_cookie(
        SESSION_COOKIE_NAME, issued.session_token, max_age=max_age, **cookie_kwargs(http_only=True)
    )
    # CSRF token: readable on purpose so the SPA can echo it in a header, but
    # only accepted when it matches the hash bound to this exact session.
    response.set_cookie(
        CSRF_COOKIE_NAME, issued.csrf_token, max_age=max_age, **cookie_kwargs(http_only=False)
    )


def clear_auth_cookies(response) -> None:
    for name, http_only in ((SESSION_COOKIE_NAME, True), (CSRF_COOKIE_NAME, False)):
        response.delete_cookie(name, **cookie_kwargs(http_only=http_only))
