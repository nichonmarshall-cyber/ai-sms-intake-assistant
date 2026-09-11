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

from sqlalchemy import select, update
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


def _configured_phone_set(settings: dict | None, key: str, env_name: str) -> set[str]:
    if settings is None or key not in settings:
        return _phone_set(env_name)
    raw = settings.get(key) or []
    values = raw.split(",") if isinstance(raw, str) else raw
    return {normalize_phone(value) for value in values if normalize_phone(value)}


def _configured_enabled(settings: dict | None, key: str, env_name: str, *, default: bool) -> bool:
    if settings is None or key not in settings:
        return _env_enabled(env_name, default=default)
    value = settings.get(key)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _cooldown_minutes(settings: dict | None = None) -> int:
    try:
        if settings is not None and "cooldown_minutes" in settings:
            return max(0, int(settings["cooldown_minutes"]))
        return max(0, int(os.getenv("MISSED_CALL_COOLDOWN_MINUTES", "5")))
    except (TypeError, ValueError):
        logger.warning("[missed_call] Invalid MISSED_CALL_COOLDOWN_MINUTES; using 5.")
        return 5


def _max_send_attempts(settings: dict | None = None) -> int:
    try:
        if settings is not None and "max_send_attempts" in settings:
            return min(5, max(1, int(settings["max_send_attempts"])))
        return min(5, max(1, int(os.getenv("MISSED_CALL_MAX_SEND_ATTEMPTS", "2"))))
    except (TypeError, ValueError):
        logger.warning("[missed_call] Invalid max send attempts; using 2.")
        return 2


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
            f"Hi, this is the {business_name} demo. Sorry we missed your call. "
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
    business_id: str | None = None,
    rules: dict | None = None,
    call_disposition: str = "",
    ignore_duplicate: bool = False,
) -> MissedCallDecision:
    """Applies the feature flag, contact, opt-out, and cooldown rules."""
    caller_phone = normalize_phone(caller_phone)
    twilio_number = normalize_phone(twilio_number)

    if not call_sid:
        return MissedCallDecision(False, "missing_call_sid")
    if call_disposition.strip().lower() in {"completed", "answered"}:
        return MissedCallDecision(False, "answered_call")
    if not _configured_enabled(rules, "enabled", "MISSED_CALLS_ENABLED", default=False):
        return MissedCallDecision(False, "feature_disabled")
    if not _is_valid_phone(caller_phone):
        return MissedCallDecision(False, "invalid_caller_number")
    if not _is_valid_phone(twilio_number):
        return MissedCallDecision(False, "invalid_twilio_number")

    if caller_phone in _configured_phone_set(rules, "blocklist", "MISSED_CALL_BLOCKLIST"):
        return MissedCallDecision(False, "blocked_caller")

    if _configured_enabled(
        rules, "require_allowlist", "MISSED_CALL_REQUIRE_ALLOWLIST", default=True
    ):
        if caller_phone not in _configured_phone_set(rules, "allowlist", "MISSED_CALL_ALLOWLIST"):
            return MissedCallDecision(False, "caller_not_allowlisted")

    session = db.execute(
        select(ConversationSession).where(
            ConversationSession.phone == caller_phone,
            ConversationSession.business_id == business_id,
        )
    ).scalar_one_or_none()
    if session is not None and session.opted_out:
        return MissedCallDecision(False, "caller_opted_out")

    if not ignore_duplicate:
        duplicate = db.execute(
            select(MissedCallEvent.id).where(MissedCallEvent.call_sid == call_sid)
        ).scalar_one_or_none()
        if duplicate is not None:
            return MissedCallDecision(False, "duplicate_call_sid")

    cooldown_minutes = _cooldown_minutes(rules)
    if cooldown_minutes:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)
        recent_message = db.execute(
            select(MissedCallEvent.id).where(
                MissedCallEvent.caller_phone == caller_phone,
                MissedCallEvent.business_id == business_id,
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
    business_id: str | None = None,
    call_status: str = "",
    call_duration_seconds: int | None = None,
) -> MissedCallEvent | None:
    """Creates the idempotency record before an outbound SMS can be sent.

    ``None`` means another worker won the unique-CallSid race; that worker is
    responsible for the one permitted outbound message.
    """
    event = MissedCallEvent(
        business_id=business_id,
        call_sid=call_sid,
        caller_phone=normalize_phone(caller_phone),
        twilio_number=normalize_phone(twilio_number),
        forwarded_from=normalize_phone(forwarded_from) or None,
        source="missed_call",
        decision="sending" if decision.allowed else decision.reason,
        call_status=(call_status or "").strip().lower() or None,
        call_duration_seconds=call_duration_seconds,
        send_attempts=1 if decision.allowed else 0,
        last_attempt_at=datetime.now(timezone.utc) if decision.allowed else None,
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
    create_args = {
        "to": caller_phone,
        "from_": twilio_number,
        "body": body,
    }
    public_base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if public_base_url:
        create_args["status_callback"] = f"{public_base_url}/voice/missed-call/status"
    message = client.messages.create(
        **create_args,
    )
    return message.sid


_DELIVERY_RANK = {"queued": 0, "sending": 1, "sent": 2, "delivered": 3}
_TERMINAL_DELIVERY_STATUSES = {"delivered", "undelivered", "failed"}


def record_delivery_status(
    db: DBSession,
    *,
    message_sid: str,
    status: str,
    error_code: str = "",
) -> bool:
    """Stores a validated, monotonic Twilio delivery callback.

    Returns ``False`` for an unknown MessageSid or unsupported status so the
    route can acknowledge the callback without mutating unrelated records.
    """
    normalized_status = (status or "").strip().lower()
    allowed = set(_DELIVERY_RANK) | {"undelivered", "failed"}
    if not message_sid or normalized_status not in allowed:
        return False

    event = db.execute(
        select(MissedCallEvent).where(MissedCallEvent.message_sid == message_sid)
    ).scalar_one_or_none()
    if event is None:
        return False

    current = (event.delivery_status or "").strip().lower()
    if current in _TERMINAL_DELIVERY_STATUSES and current != normalized_status:
        return True
    if (
        current in _DELIVERY_RANK
        and normalized_status in _DELIVERY_RANK
        and _DELIVERY_RANK[normalized_status] < _DELIVERY_RANK[current]
    ):
        return True

    event.delivery_status = normalized_status
    event.error_code = (
        (error_code or "").strip()[:64]
        if normalized_status in {"undelivered", "failed"}
        else None
    )
    db.add(event)
    db.commit()
    return True


def process_missed_call(
    db: DBSession,
    *,
    caller_phone: str,
    twilio_number: str,
    forwarded_from: str,
    call_sid: str,
    business_name: str,
    is_demo: bool,
    business_id: str | None = None,
    rules: dict | None = None,
    call_status: str = "",
    call_disposition: str = "",
    call_duration_seconds: int | None = None,
) -> MissedCallOutcome:
    """Records a forwarded call and sends its single permitted follow-up SMS."""
    decision = should_start_missed_call_intake(
        db,
        caller_phone=caller_phone,
        twilio_number=twilio_number,
        call_sid=call_sid,
        business_id=business_id,
        rules=rules,
        call_disposition=call_disposition,
    )

    if not call_sid:
        logger.warning("[missed_call] Ignored webhook without CallSid.")
        return MissedCallOutcome(decision=decision, message_sent=False)

    event = None
    if decision.reason == "duplicate_call_sid":
        event = db.execute(
            select(MissedCallEvent).where(MissedCallEvent.call_sid == call_sid)
        ).scalar_one_or_none()
        if event is None or event.decision != "send_failed":
            return MissedCallOutcome(decision=decision, message_sent=False)

        retry_decision = should_start_missed_call_intake(
            db,
            caller_phone=caller_phone,
            twilio_number=twilio_number,
            call_sid=call_sid,
            business_id=business_id,
            rules=rules,
            call_disposition=call_disposition,
            ignore_duplicate=True,
        )
        if not retry_decision.allowed:
            return MissedCallOutcome(decision=retry_decision, message_sent=False)

        max_attempts = _max_send_attempts(rules)
        if event.send_attempts >= max_attempts:
            return MissedCallOutcome(
                decision=MissedCallDecision(False, "retry_exhausted"),
                message_sent=False,
            )
        claimed = db.execute(
            update(MissedCallEvent)
            .where(
                MissedCallEvent.id == event.id,
                MissedCallEvent.decision == "send_failed",
                MissedCallEvent.send_attempts < max_attempts,
            )
            .values(
                decision="retrying",
                send_attempts=MissedCallEvent.send_attempts + 1,
                last_attempt_at=datetime.now(timezone.utc),
                error_code=None,
            )
        )
        db.commit()
        if claimed.rowcount != 1:
            return MissedCallOutcome(
                decision=MissedCallDecision(False, "duplicate_call_sid"),
                message_sent=False,
            )
        db.refresh(event)
        decision = MissedCallDecision(True, "retrying")
    else:
        event = _record_event(
            db,
            call_sid=call_sid,
            caller_phone=caller_phone,
            twilio_number=twilio_number,
            forwarded_from=forwarded_from,
            decision=decision,
            business_id=business_id,
            call_status=call_status,
            call_duration_seconds=call_duration_seconds,
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
    except Exception as exc:
        event.decision = "send_failed"
        event.delivery_status = "failed"
        event.error_code = str(getattr(exc, "code", None) or "send_error")[:64]
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
    event.delivery_status = "queued"
    event.error_code = None
    db.add(event)
    db.commit()
    logger.info(
        "[missed_call] CallSid=%s caller=%s destination=%s decision=sent",
        call_sid,
        mask_phone(caller_phone),
        mask_phone(twilio_number),
    )
    return MissedCallOutcome(decision=MissedCallDecision(True, "sent"), message_sent=True)
