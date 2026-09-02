"""Rules and delivery helpers for missed-call SMS follow-up.

The Flask route deliberately stays thin: this module owns the decision about
whether a caller may receive an initial message, records every attempt, and
sends the outbound SMS only after the CallSid has been durably recorded.  That
keeps the demo safe today and gives production deployments one place to add
per-client settings later.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession
from twilio.rest import Client

from modules.conversation_store import normalize_phone
from modules.models import ConversationSession, MissedCallEvent

logger = logging.getLogger(__name__)

_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")


@dataclass(frozen=True)
class MissedCallDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class MissedCallOutcome:
    decision: MissedCallDecision
    message_sent: bool


def _env_enabled(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _phone_set(name: str) -> set[str]:
    return {
        normalize_phone(value)
        for value in os.getenv(name, "").split(",")
        if normalize_phone(value)
    }


def _cooldown_minutes() -> int:
    try:
        return max(0, int(os.getenv("MISSED_CALL_COOLDOWN_MINUTES", "5")))
    except ValueError:
        logger.warning("[missed_call] Invalid MISSED_CALL_COOLDOWN_MINUTES; using 5.")
        return 5


def _is_valid_phone(number: str) -> bool:
    return bool(_E164_RE.fullmatch(normalize_phone(number)))


def mask_phone(number: str) -> str:
    """Returns a log-safe representation of a phone number."""
    normalized = normalize_phone(number)
    if len(normalized) <= 4:
        return "***"
    return f"***{normalized[-4:]}"


def initial_sms_text(*, business_name: str, is_demo: bool) -> str:
    if is_demo:
        return (
            "Hi, this is the NTX Automation Co. demo. Sorry we missed your call. "
            "Reply DEMO or MENU to explore the intake assistant. Reply STOP to opt out."
        )
    return (
        f"Hi, this is {business_name}. Sorry we missed your call. "
        "What can we help you with? Reply STOP to opt out."
    )


def should_start_missed_call_intake(
    db: DBSession,
    *,
    caller_phone: str,
    twilio_number: str,
    call_sid: str,
) -> MissedCallDecision:
    """Applies the feature flag, contact, opt-out, and cooldown rules."""
    caller_phone = normalize_phone(caller_phone)
    twilio_number = normalize_phone(twilio_number)

    if not call_sid:
        return MissedCallDecision(False, "missing_call_sid")
    if not _env_enabled("MISSED_CALLS_ENABLED"):
        return MissedCallDecision(False, "feature_disabled")
    if not _is_valid_phone(caller_phone):
        return MissedCallDecision(False, "invalid_caller_number")
    if not _is_valid_phone(twilio_number):
        return MissedCallDecision(False, "invalid_twilio_number")

    if caller_phone in _phone_set("MISSED_CALL_BLOCKLIST"):
        return MissedCallDecision(False, "blocked_caller")

    if _env_enabled("MISSED_CALL_REQUIRE_ALLOWLIST", default=True):
        if caller_phone not in _phone_set("MISSED_CALL_ALLOWLIST"):
            return MissedCallDecision(False, "caller_not_allowlisted")

    session = db.execute(
        select(ConversationSession).where(ConversationSession.phone == caller_phone)
    ).scalar_one_or_none()
    if session is not None and session.opted_out:
        return MissedCallDecision(False, "caller_opted_out")

    duplicate = db.execute(
        select(MissedCallEvent.id).where(MissedCallEvent.call_sid == call_sid)
    ).scalar_one_or_none()
    if duplicate is not None:
        return MissedCallDecision(False, "duplicate_call_sid")

    cooldown_minutes = _cooldown_minutes()
    if cooldown_minutes:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)
        recent_message = db.execute(
            select(MissedCallEvent.id).where(
                MissedCallEvent.caller_phone == caller_phone,
                MissedCallEvent.message_sid.is_not(None),
                MissedCallEvent.created_at >= cutoff,
            )
        ).scalar_one_or_none()
        if recent_message is not None:
            return MissedCallDecision(False, "cooldown_active")

    return MissedCallDecision(True, "allowed")


def _record_event(
    db: DBSession,
    *,
    call_sid: str,
    caller_phone: str,
    twilio_number: str,
    forwarded_from: str,
    decision: MissedCallDecision,
) -> MissedCallEvent | None:
    """Creates the idempotency record before an outbound SMS can be sent.

    ``None`` means another worker won the unique-CallSid race; that worker is
    responsible for the one permitted outbound message.
    """
    event = MissedCallEvent(
        call_sid=call_sid,
        caller_phone=normalize_phone(caller_phone),
        twilio_number=normalize_phone(twilio_number),
        forwarded_from=normalize_phone(forwarded_from) or None,
        source="missed_call",
        decision=decision.reason,
    )
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.info("[missed_call] Concurrent duplicate CallSid=%s suppressed.", call_sid)
        return None
    db.refresh(event)
    return event


def _send_initial_sms(*, caller_phone: str, twilio_number: str, body: str) -> str:
    """Sends from the exact Twilio number that received the forwarded call."""
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    if not account_sid or not auth_token:
        raise RuntimeError("Twilio credentials are missing.")

    client = Client(account_sid, auth_token)
    message = client.messages.create(
        to=caller_phone,
        from_=twilio_number,
        body=body,
    )
    return message.sid


def process_missed_call(
    db: DBSession,
    *,
    caller_phone: str,
    twilio_number: str,
    forwarded_from: str,
    call_sid: str,
    business_name: str,
    is_demo: bool,
) -> MissedCallOutcome:
    """Records a forwarded call and sends its single permitted follow-up SMS."""
    decision = should_start_missed_call_intake(
        db,
        caller_phone=caller_phone,
        twilio_number=twilio_number,
        call_sid=call_sid,
    )

    if not call_sid:
        logger.warning("[missed_call] Ignored webhook without CallSid.")
        return MissedCallOutcome(decision=decision, message_sent=False)

    event = _record_event(
        db,
        call_sid=call_sid,
        caller_phone=caller_phone,
        twilio_number=twilio_number,
        forwarded_from=forwarded_from,
        decision=decision,
    )
    if event is None:
        return MissedCallOutcome(
            decision=MissedCallDecision(False, "duplicate_call_sid"),
            message_sent=False,
        )

    if not decision.allowed:
        logger.info(
            "[missed_call] CallSid=%s caller=%s destination=%s decision=%s",
            call_sid,
            mask_phone(caller_phone),
            mask_phone(twilio_number),
            decision.reason,
        )
        return MissedCallOutcome(decision=decision, message_sent=False)

    try:
        message_sid = _send_initial_sms(
            caller_phone=normalize_phone(caller_phone),
            twilio_number=normalize_phone(twilio_number),
            body=initial_sms_text(business_name=business_name, is_demo=is_demo),
        )
    except Exception:
        event.decision = "send_failed"
        db.add(event)
        db.commit()
        logger.exception(
            "[missed_call] CallSid=%s caller=%s initial SMS failed.",
            call_sid,
            mask_phone(caller_phone),
        )
        return MissedCallOutcome(
            decision=MissedCallDecision(False, "send_failed"),
            message_sent=False,
        )

    event.decision = "sent"
    event.message_sid = message_sid
    db.add(event)
    db.commit()
    logger.info(
        "[missed_call] CallSid=%s caller=%s destination=%s decision=sent",
        call_sid,
        mask_phone(caller_phone),
        mask_phone(twilio_number),
    )
    return MissedCallOutcome(decision=MissedCallDecision(True, "sent"), message_sent=True)
