"""One-time password reset issuance and consumption."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session as DBSession

from modules.auth.crypto import hash_ip, hash_token, new_token, tokens_match
from modules.models import PasswordResetToken


TOKEN_TTL = timedelta(minutes=30)
RATE_WINDOW = timedelta(minutes=15)
MAX_REQUESTS_PER_WINDOW = 3


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def rate_limited(db: DBSession, *, user_id: str | None, raw_ip: str | None) -> bool:
    since = _utcnow() - RATE_WINDOW
    clauses = [PasswordResetToken.created_at >= since]
    identities = []
    if user_id:
        identities.append(PasswordResetToken.user_id == user_id)
    ip_digest = hash_ip(raw_ip)
    if ip_digest:
        identities.append(PasswordResetToken.ip_hash == ip_digest)
    if not identities:
        return False
    from sqlalchemy import or_

    total = db.scalar(select(func.count()).select_from(PasswordResetToken).where(*clauses, or_(*identities)))
    return int(total or 0) >= MAX_REQUESTS_PER_WINDOW


def issue(db: DBSession, *, user_id: str, raw_ip: str | None) -> str:
    now = _utcnow()
    # A new request invalidates previous live links for this user.
    db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user_id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )
    raw = new_token()
    db.add(
        PasswordResetToken(
            user_id=user_id,
            token_hash=hash_token(raw),
            ip_hash=hash_ip(raw_ip),
            created_at=now,
            expires_at=now + TOKEN_TTL,
        )
    )
    db.flush()
    return raw


def consume(db: DBSession, raw_token: str) -> PasswordResetToken | None:
    if not raw_token:
        return None
    row = db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == hash_token(raw_token),
            PasswordResetToken.used_at.is_(None),
        )
    ).scalar_one_or_none()
    if row is None or not tokens_match(raw_token, row.token_hash):
        return None
    now = _utcnow()
    if _as_aware(row.expires_at) <= now:
        row.used_at = now
        return None
    row.used_at = now
    return row
