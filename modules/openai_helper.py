"""
openai_helper.py
Handles all OpenAI API communication.

Improvements:
- Adds request timeout (read from OPENAI_TIMEOUT_SECONDS env var)
- Safely handles missing/empty choices
- Validates top-level fields and extracted field types
- Aligns fallback with reality: category='unknown', termination_reason='error'
- Includes vehicle fields in extracted_fields validation
- Trims reply/business_summary strings via _normalize()
- Logs better failure context for debugging
- Strips unknown keys from extracted_fields before returning (allowlist guard)
"""

import os
import json
import logging
from openai import OpenAI
from modules.prompt import build_system_prompt
from modules.business_hours import is_business_hours

logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ─── Validation constants ────────────────────────────────────────────────────

REQUIRED_TOP_LEVEL = [
    "reply",
    "category",
    "extracted_fields",
    "is_complete",
    "business_summary",
    "topic_status",
    "should_terminate",
    "termination_reason",
]

REQUIRED_EXTRACTED = [
    "customer_name",
    "service_description",
    "callback_requested",
    "callback_day",
    "preferred_time",
    "vehicle_year",
    "vehicle_make",
    "vehicle_model",
]

# Match these to prompt.py exactly
VALID_CATEGORIES = {
    "diagnostic",
    "tire_service",
    "oil_change",
    "detailing",
    "power_washing",
    "quote_request",
    "general_service",
    "unknown",
}

VALID_TOPIC_STATUSES = {"on_topic", "off_topic", "unsafe"}

VALID_TERMINATION_REASONS = {
    "completed",
    "off_topic",
    "unsafe",
    "max_turns",
    "error",
    None,
}

# Allowlist of keys permitted in extracted_fields.
# Any key the AI returns outside this set is silently dropped before the
# result reaches merge_fields() in conversation.py.
ALLOWED_FIELD_KEYS = set(REQUIRED_EXTRACTED)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _is_nullable_string(value) -> bool:
    return value is None or isinstance(value, str)


def _last_user_message(conversation_history: list[dict]) -> str:
    for message in reversed(conversation_history):
        if message.get("role") == "user":
            return str(message.get("content", ""))
    return ""


# ─── Validation ──────────────────────────────────────────────────────────────

def _validate(data: dict) -> tuple[bool, str]:
    """
    Returns (True, "") if the response is valid.
    Returns (False, reason) if any field is missing or invalid.
    """
    if not isinstance(data, dict):
        return False, "Top-level response must be a JSON object"

    for field in REQUIRED_TOP_LEVEL:
        if field not in data:
            return False, f"Missing top-level field: '{field}'"

    if not isinstance(data["extracted_fields"], dict):
        return False, "'extracted_fields' must be a dict"

    for field in REQUIRED_EXTRACTED:
        if field not in data["extracted_fields"]:
            return False, f"Missing extracted field: '{field}'"

    if data["category"] not in VALID_CATEGORIES:
        return False, f"Invalid category: '{data['category']}'"

    if data["topic_status"] not in VALID_TOPIC_STATUSES:
        return False, f"Invalid topic_status: '{data['topic_status']}'"

    if data["termination_reason"] not in VALID_TERMINATION_REASONS:
        return False, f"Invalid termination_reason: '{data['termination_reason']}'"

    if not isinstance(data["is_complete"], bool):
        return False, "'is_complete' must be boolean"

    if not isinstance(data["should_terminate"], bool):
        return False, "'should_terminate' must be boolean"

    if not isinstance(data["reply"], str) or not data["reply"].strip():
        return False, "'reply' must be a non-empty string"

    extracted = data["extracted_fields"]

    if not isinstance(extracted["callback_requested"], bool):
        return False, "'callback_requested' must be boolean"

    nullable_string_fields = [
        "customer_name",
        "service_description",
        "callback_day",
        "preferred_time",
        "vehicle_year",
        "vehicle_make",
        "vehicle_model",
    ]

    for field in nullable_string_fields:
        if not _is_nullable_string(extracted[field]):
            return False, f"'{field}' must be a string or null"

    if not _is_nullable_string(data["business_summary"]):
        return False, "'business_summary' must be a string or null"

    return True, ""


def _normalize(data: dict) -> dict:
    """
    Cleans up whitespace so downstream code gets consistent values.
    Also strips unknown keys from extracted_fields (allowlist guard).
    """
    data["reply"] = data["reply"].strip()

    if isinstance(data["business_summary"], str):
        data["business_summary"] = data["business_summary"].strip() or None

    extracted = data["extracted_fields"]

    # Strip whitespace and convert empty strings to None
    for key, value in list(extracted.items()):
        if isinstance(value, str):
            cleaned = value.strip()
            extracted[key] = cleaned if cleaned else None

    # Drop any keys not in the allowlist
    data["extracted_fields"] = {
        k: v for k, v in extracted.items()
        if k in ALLOWED_FIELD_KEYS
    }

    return data


# ─── Public API ──────────────────────────────────────────────────────────────

def get_ai_response(conversation_history: list[dict]) -> dict:
    """
    Sends the full conversation history to OpenAI and returns a validated
    structured response dict.

    Args:
        conversation_history: List of {"role": ..., "content": ...} dicts.
            Do NOT include the system prompt here — it is prepended here.

    Returns:
        Validated dict with all required fields, or a safe fallback.
    """
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    system_prompt = build_system_prompt(is_business_hours())
    timeout_seconds = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "10"))

    messages = [{"role": "system", "content": system_prompt}] + conversation_history
    last_user = _last_user_message(conversation_history)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=600,
            response_format={"type": "json_object"},
            timeout=timeout_seconds,
        )

        if not getattr(response, "choices", None):
            logger.error("[openai] No choices returned from API.")
            return _fallback(
                reason="No choices returned from API",
                conversation_history=conversation_history,
            )

        message = response.choices[0].message
        raw = getattr(message, "content", None)

        if raw is None or not str(raw).strip():
            logger.error("[openai] Empty content returned from API.")
            return _fallback(
                reason="Empty content returned from API",
                conversation_history=conversation_history,
            )

        logger.debug(f"[openai] Raw response: {raw}")

        data = json.loads(raw)
        valid, error = _validate(data)

        if not valid:
            logger.error(
                "[openai] Validation failed — %s | Last user message: %r | Raw: %s",
                error,
                last_user,
                raw,
            )
            return _fallback(
                reason=f"Validation error: {error}",
                conversation_history=conversation_history,
            )

        return _normalize(data)

    except json.JSONDecodeError as e:
        logger.error(
            "[openai] JSON decode error: %s | Last user message: %r",
            e,
            last_user,
        )
        return _fallback(
            reason=f"JSON decode error: {e}",
            conversation_history=conversation_history,
        )

    except Exception as e:
        logger.exception(
            "[openai] Unexpected error during OpenAI call | Last user message: %r",
            last_user,
        )
        return _fallback(
            reason=str(e),
            conversation_history=conversation_history,
        )


def _fallback(reason: str, conversation_history: list[dict] | None = None) -> dict:
    """
    Safe response used when OpenAI returns something invalid or fails entirely.
    Always terminates the session to prevent an uncontrolled loop.
    """
    last_user = _last_user_message(conversation_history or [])

    logger.error(
        "[openai] Using fallback | reason=%s | last_user=%r",
        reason,
        last_user,
    )

    return {
        "reply": (
            "Sorry, we ran into an issue on our end. The team will follow "
            "up with you directly. Thanks for your patience!"
        ),
        "category": "unknown",
        "extracted_fields": {
            "customer_name": None,
            "service_description": None,
            "callback_requested": False,
            "callback_day": None,
            "preferred_time": None,
            "vehicle_year": None,
            "vehicle_make": None,
            "vehicle_model": None,
        },
        "is_complete": False,
        "business_summary": "AI failure — fallback triggered.",
        "topic_status": "on_topic",
        "should_terminate": True,
        "termination_reason": "error",
    }
