"""
conversation_store.py
PostgreSQL/SQLite-backed conversation session storage, replacing the old
process-only in-memory dict. This is the only module that touches
ConversationSession rows directly.

Session lifecycle:
  - Sessions are keyed by normalized phone number.
  - SESSION_TTL_MINUTES (default 45) of inactivity expires a session.
    The next inbound message after expiration starts a brand new session
    (fresh state, fresh profile selection in demo mode).
  - Demo mode sessions start in "awaiting_profile_selection"; production
    mode sessions start directly "in_progress" against DEFAULT_PROFILE.
"""

import os
import re
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from modules.models import ConversationSession, Lead, ProcessedMessage

logger = logging.getLogger(__name__)

# Allowlist guard mirrored from the legacy conversation.py — any field key
# the AI returns that isn't part of the active profile's schema is dropped
# before it ever reaches the database.
_MAX_HISTORY = int(os.getenv("MAX_HISTORY", 12))
_MAX_TURNS = int(os.getenv("MAX_TURNS", 15))


def get_session_ttl_minutes() -> int:
    return int(os.getenv("SESSION_TTL_MINUTES", 45))


def normalize_phone(raw: str) -> str:
    """
    Normalizes a phone number for use as a stable session key.
    Keeps a leading '+' if present, strips all other non-digit characters.
    """
    raw = (raw or "").strip()
    if not raw:
        return raw
    has_plus = raw.startswith("+")
    digits = re.sub(r"\D", "", raw)
    return f"+{digits}" if has_plus else digits


def _new_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=get_session_ttl_minutes())


def _as_aware_utc(dt: datetime) -> datetime:
    """
    SQLite does not actually persist timezone awareness (unlike Postgres),
    so a DateTime(timezone=True) column round-trips as naive on SQLite.
    Everything we store is UTC, so a naive value is treated as UTC.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _initial_state(is_demo: bool) -> str:
    return "awaiting_profile_selection" if is_demo else "in_progress"


def get_or_create_session(
    db: DBSession,
    phone: str,
    *,
    is_demo: bool,
    default_profile_key: str | None,
) -> tuple[ConversationSession, bool]:
    """
    Returns (session, is_new). A session is considered "new" both when no
    row exists yet and when the existing row has expired (TTL elapsed) or
    was already terminated — in both cases a fresh row replaces it.
    """
    phone = normalize_phone(phone)
    now = datetime.now(timezone.utc)

    existing = db.execute(
        select(ConversationSession).where(ConversationSession.phone == phone)
    ).scalar_one_or_none()

    expired = existing is not None and (_as_aware_utc(existing.expires_at) < now or existing.terminated)

    if existing is not None and not expired:
        return existing, False

    carried_opt_out = False
    if existing is not None and expired:
        logger.info(f"[conversation_store] Session expired/terminated for {phone} — starting fresh.")
        carried_opt_out = existing.opted_out  # opt-out survives session TTL/reset
        db.delete(existing)
        db.flush()

    session = ConversationSession(
        phone=phone,
        state=_initial_state(is_demo),
        profile_key=None if is_demo else default_profile_key,
        history=[],
        fields={},
        turn_count=0,
        off_topic_strikes=0,
        terminated=False,
        opted_out=carried_opt_out,
        expires_at=_new_expiry(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session, True


def touch(db: DBSession, session: ConversationSession) -> None:
    session.expires_at = _new_expiry()
    db.add(session)
    db.commit()


def set_profile(db: DBSession, session: ConversationSession, profile_key: str) -> None:
    """Selects (or switches) the active profile, resetting per-profile state."""
    session.profile_key = profile_key
    session.state = "in_progress"
    session.history = []
    session.fields = {}
    session.turn_count = 0
    session.off_topic_strikes = 0
    session.terminated = False
    session.expires_at = _new_expiry()
    db.add(session)
    db.commit()


def reset_to_menu(db: DBSession, session: ConversationSession) -> None:
    """Used by MENU/START/DEMO — returns a demo session to profile selection."""
    session.state = "awaiting_profile_selection"
    session.profile_key = None
    session.history = []
    session.fields = {}
    session.turn_count = 0
    session.off_topic_strikes = 0
    session.terminated = False
    session.expires_at = _new_expiry()
    db.add(session)
    db.commit()


def add_user_message(db: DBSession, session: ConversationSession, text: str) -> None:
    history = list(session.history or [])
    history.append({"role": "user", "content": text})
    session.history = history[-_MAX_HISTORY:]
    db.add(session)
    db.commit()


def add_assistant_message(db: DBSession, session: ConversationSession, text: str) -> None:
    history = list(session.history or [])
    history.append({"role": "assistant", "content": text})
    session.history = history[-_MAX_HISTORY:]
    session.turn_count = (session.turn_count or 0) + 1
    db.add(session)
    db.commit()


def merge_fields(
    db: DBSession, session: ConversationSession, new_fields: dict, allowed_keys: set[str]
) -> None:
    """
    Merges newly extracted fields. Only keys in allowed_keys (the active
    profile's schema) are accepted. Existing non-null values are never
    overwritten, so data is never lost between turns.
    """
    fields = dict(session.fields or {})
    for key, value in (new_fields or {}).items():
        if key not in allowed_keys:
            logger.warning(f"[conversation_store] Dropping unknown field key: '{key}'")
            continue
        if value is not None and fields.get(key) in (None, ""):
            fields[key] = value
    session.fields = fields
    db.add(session)
    db.commit()


def is_at_max_turns(session: ConversationSession) -> bool:
    return (session.turn_count or 0) >= _MAX_TURNS


def increment_off_topic(db: DBSession, session: ConversationSession) -> int:
    session.off_topic_strikes = (session.off_topic_strikes or 0) + 1
    db.add(session)
    db.commit()
    return session.off_topic_strikes


def reset_off_topic_strikes(db: DBSession, session: ConversationSession) -> None:
    if session.off_topic_strikes:
        session.off_topic_strikes = 0
        db.add(session)
        db.commit()


def mark_terminated(db: DBSession, session: ConversationSession) -> None:
    session.terminated = True
    session.state = "completed"
    db.add(session)
    db.commit()


def mark_opted_out(db: DBSession, session: ConversationSession, opted_out: bool) -> None:
    session.opted_out = opted_out
    db.add(session)
    db.commit()


def reset_session(db: DBSession, phone: str) -> bool:
    phone = normalize_phone(phone)
    existing = db.execute(
        select(ConversationSession).where(ConversationSession.phone == phone)
    ).scalar_one_or_none()
    if existing is None:
        return False
    db.delete(existing)
    db.commit()
    return True


def reset_all_sessions(db: DBSession) -> int:
    rows = db.execute(select(ConversationSession)).scalars().all()
    count = len(rows)
    for row in rows:
        db.delete(row)
    db.commit()
    return count


# ─── Leads ─────────────────────────────────────────────────────────────────

def record_lead(
    db: DBSession,
    session: ConversationSession,
    ai_result: dict,
    status: str,
) -> Lead:
    lead = Lead(
        phone=session.phone,
        profile_key=session.profile_key or "unknown",
        fields=dict(session.fields or {}),
        status=status,
        category=ai_result.get("category"),
        business_summary=ai_result.get("business_summary"),
        termination_reason=ai_result.get("termination_reason"),
        turn_count=session.turn_count or 0,
        off_topic_strikes=session.off_topic_strikes or 0,
        is_complete=bool(ai_result.get("is_complete", False)),
        requested_callback_time=(session.fields or {}).get("preferred_callback_time"),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


# ─── Webhook idempotency ────────────────────────────────────────────────────

def find_processed_message(db: DBSession, message_sid: str) -> ProcessedMessage | None:
    if not message_sid:
        return None
    return db.execute(
        select(ProcessedMessage).where(ProcessedMessage.message_sid == message_sid)
    ).scalar_one_or_none()


def record_processed_message(
    db: DBSession, message_sid: str, phone: str, response_body: str
) -> None:
    if not message_sid:
        return
    db.add(
        ProcessedMessage(
            message_sid=message_sid,
            phone=normalize_phone(phone),
            response_body=response_body[:2000] if response_body else None,
        )
    )
    db.commit()
