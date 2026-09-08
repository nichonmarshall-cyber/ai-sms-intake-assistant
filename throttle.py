"""PostgreSQL-backed login throttle.

Flask-Limiter's default ``memory://`` storage is per-process. With Gunicorn
running multiple workers that silently multiplies the allowance, so login
protection is kept in the database instead where every worker sees the same
counters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from modules.auth.crypto import hash_ip
from modules.models import LoginAttempt


WINDOW = timedelta(minutes=15)
MAX_FAILURES_PER_EMAIL = 5
MAX_FAILURES_PER_IP = 20


@dataclass(frozen=True)
class ThrottleDecision:
    allowed: bool
    retry_after_seconds: int = 0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _failures_since(db: DBSession, *, column, value, since: datetime) -> int:
    if value is None:
        return 0
    return int(
        db.execute(
            select(func.count())
            .select_from(LoginAttempt)
            .where(column == value, LoginAttempt.success.is_(False), LoginAttempt.created_at >= since)
        ).scalar_one()
    )


def check(db: DBSession, *, email: str | None, raw_ip: str | None) -> ThrottleDecision:
    """Returns whether this login attempt may proceed."""
    since = _utcnow() - WINDOW
    email_lower = (email or "").strip().lower() or None
    ip_digest = hash_ip(raw_ip)

    email_failures = _failures_since(
        db, column=LoginAttempt.email_lower, value=email_lower, since=since
    )
    if email_failures >= MAX_FAILURES_PER_EMAIL:
        return ThrottleDecision(False, int(WINDOW.total_seconds()))

    ip_failures = _failures_since(db, column=LoginAttempt.ip_hash, value=ip_digest, since=since)
    if ip_failures >= MAX_FAILURES_PER_IP:
        return ThrottleDecision(False, int(WINDOW.total_seconds()))

    return ThrottleDecision(True)


def record(db: DBSession, *, email: str | None, raw_ip: str | None, success: bool) -> None:
    db.add(
        LoginAttempt(
            email_lower=(email or "").strip().lower() or None,
            ip_hash=hash_ip(raw_ip),
            success=success,
        )
    )
    db.commit()
