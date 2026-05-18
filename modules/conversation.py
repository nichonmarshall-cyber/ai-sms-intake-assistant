"""
conversation.py
Manages in-memory conversation state, keyed by phone number.

Each session holds:
  - history          : full OpenAI-format message list (capped at MAX_HISTORY)
  - fields           : accumulated extracted lead data
  - turn_count       : number of assistant replies sent
  - terminated       : whether the conversation has ended
  - off_topic_strikes: how many consecutive off-topic messages have been sent
  - started_at       : UTC ISO timestamp of session creation

Fixes applied:
  - _empty_fields() now includes vehicle_year, vehicle_make, vehicle_model
  - merge_fields() rejects keys not in ALLOWED_FIELD_KEYS (allowlist guard)
  - History is capped at MAX_HISTORY messages (oldest trimmed first)
  - reset_off_topic_strikes() added for when user returns to on-topic

Future upgrade: swap _sessions dict for Redis or a database without
touching any other file — this module is the only state layer.
"""

import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# { phone_number (str) : session (dict) }
_sessions: dict[str, dict] = {}

MAX_TURNS   = int(os.getenv("MAX_TURNS", 15))

# Cap on messages kept in history sent to OpenAI.
# 12 = 6 user + 6 assistant messages — tight context window, lower token cost.
MAX_HISTORY = int(os.getenv("MAX_HISTORY", 12))

# Allowlist of field keys that may be written into session state.
# Any key outside this set returned by the AI is silently dropped.
ALLOWED_FIELD_KEYS = {
    "customer_name",
    "service_description",
    "callback_requested",
    "callback_day",
    "preferred_time",
    "vehicle_year",
    "vehicle_make",
    "vehicle_model",
}


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _empty_fields() -> dict:
    """Returns a blank extracted-fields dict matching the AI output contract."""
    return {
        "customer_name":      None,
        "service_description": None,
        "callback_requested": False,
        "callback_day":       None,
        "preferred_time":     None,
        "vehicle_year":       None,
        "vehicle_make":       None,
        "vehicle_model":      None,
    }


def _trim_history(history: list) -> list:
    """
    Returns the history trimmed to MAX_HISTORY messages.
    Oldest messages are dropped first. Called after every append.
    """
    if len(history) > MAX_HISTORY:
        return history[-MAX_HISTORY:]
    return history


# ─── Session lifecycle ────────────────────────────────────────────────────────

def get_session(phone: str) -> dict:
    """Returns the session for a phone number, creating one if needed."""
    if phone not in _sessions:
        logger.info(f"[conversation] New session: {phone}")
        _sessions[phone] = {
            "phone":               phone,
            "history":             [],
            "fields":              _empty_fields(),
            "turn_count":          0,
            "terminated":          False,
            "off_topic_strikes":   0,
            "started_at":          datetime.now(timezone.utc).isoformat(),
        }
    return _sessions[phone]


def session_exists(phone: str) -> bool:
    return phone in _sessions


def reset_session(phone: str) -> None:
    """Removes a single session. Used by the /reset endpoint during testing."""
    if phone in _sessions:
        del _sessions[phone]
        logger.info(f"[conversation] Session reset: {phone}")


def reset_all_sessions() -> int:
    """Removes all sessions. Returns the count cleared."""
    count = len(_sessions)
    _sessions.clear()
    logger.info(f"[conversation] All {count} session(s) cleared.")
    return count


# ─── Message management ───────────────────────────────────────────────────────

def add_user_message(phone: str, text: str) -> None:
    session = get_session(phone)
    session["history"].append({"role": "user", "content": text})
    session["history"] = _trim_history(session["history"])


def add_assistant_message(phone: str, text: str) -> None:
    session = get_session(phone)
    session["history"].append({"role": "assistant", "content": text})
    session["history"] = _trim_history(session["history"])
    session["turn_count"] += 1


def get_history(phone: str) -> list[dict]:
    """Returns the trimmed history — safe to pass directly to OpenAI."""
    return get_session(phone)["history"]


# ─── Field accumulation ───────────────────────────────────────────────────────

def merge_fields(phone: str, new_fields: dict) -> None:
    """
    Merges newly extracted fields into the session.

    Rules:
    - Only keys in ALLOWED_FIELD_KEYS are accepted (unknown keys dropped).
    - Existing non-null values are never overwritten — data is never lost
      between turns.
    """
    session = get_session(phone)
    for key, value in new_fields.items():
        if key not in ALLOWED_FIELD_KEYS:
            logger.warning(f"[conversation] Dropping unknown field key: '{key}'")
            continue
        if value is not None:
            session["fields"][key] = value


def get_fields(phone: str) -> dict:
    return get_session(phone)["fields"]


# ─── State checks ─────────────────────────────────────────────────────────────

def is_terminated(phone: str) -> bool:
    return get_session(phone).get("terminated", False)


def is_at_max_turns(phone: str) -> bool:
    return get_session(phone)["turn_count"] >= MAX_TURNS


def mark_terminated(phone: str) -> None:
    get_session(phone)["terminated"] = True
    logger.info(f"[conversation] Session terminated: {phone}")


def increment_off_topic(phone: str) -> int:
    """Increments and returns the off-topic strike count."""
    session = get_session(phone)
    session["off_topic_strikes"] += 1
    return session["off_topic_strikes"]


def reset_off_topic_strikes(phone: str) -> None:
    """
    Resets off-topic strike count to zero.
    Called when the user returns to on-topic conversation so a past
    strike doesn't linger and cause premature termination.
    """
    session = get_session(phone)
    if session["off_topic_strikes"] > 0:
        session["off_topic_strikes"] = 0
        logger.info(f"[conversation] Off-topic strikes reset for {phone}")
