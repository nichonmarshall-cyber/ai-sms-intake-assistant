"""
openai_helper.py
Handles all OpenAI API communication.

Generalized for the multi-industry demo: validation is driven by the
active Profile's field schema and category list instead of a hardcoded
mechanic shape. Everything else (timeout handling, safe fallback,
allowlist stripping of unknown keys) is unchanged in spirit from the
mechanic-only version.
"""

import os
import json
import logging
from openai import OpenAI

from modules.profiles import Profile
from modules.prompt import build_system_prompt

logger = logging.getLogger(__name__)

_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


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

VALID_TOPIC_STATUSES = {"on_topic", "off_topic", "unsafe"}

VALID_TERMINATION_REASONS = {
    "completed",
    "off_topic",
    "unsafe",
    "max_turns",
    "error",
    None,
}


def _is_nullable_string(value) -> bool:
    return value is None or isinstance(value, str)


def _last_user_message(conversation_history: list[dict]) -> str:
    for message in reversed(conversation_history):
        if message.get("role") == "user":
            return str(message.get("content", ""))
    return ""


def _validate(data: dict, profile: Profile) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "Top-level response must be a JSON object"

    for field in REQUIRED_TOP_LEVEL:
        if field not in data:
            return False, f"Missing top-level field: '{field}'"

    if not isinstance(data["extracted_fields"], dict):
        return False, "'extracted_fields' must be a dict"

    extracted = data["extracted_fields"]
    for field_spec in profile.fields:
        if field_spec.key not in extracted:
            return False, f"Missing extracted field: '{field_spec.key}'"
        if not _is_nullable_string(extracted[field_spec.key]):
            return False, f"'{field_spec.key}' must be a string or null"

    if data["category"] not in profile.categories:
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

    if not _is_nullable_string(data["business_summary"]):
        return False, "'business_summary' must be a string or null"

    return True, ""


def _normalize(data: dict, profile: Profile) -> dict:
    data["reply"] = data["reply"].strip()

    if isinstance(data["business_summary"], str):
        data["business_summary"] = data["business_summary"].strip() or None

    extracted = data["extracted_fields"]
    for key, value in list(extracted.items()):
        if isinstance(value, str):
            cleaned = value.strip()
            extracted[key] = cleaned if cleaned else None

    allowed_keys = set(profile.field_keys())
    data["extracted_fields"] = {k: v for k, v in extracted.items() if k in allowed_keys}

    return data


def get_ai_response(
    conversation_history: list[dict],
    *,
    profile: Profile,
    is_demo: bool,
    is_business_hours: bool,
    business_name: str,
    next_field,
) -> dict:
    """
    Sends the full conversation history to OpenAI and returns a validated
    structured response dict, scoped to the active profile's field schema.

    Args:
        conversation_history: List of {"role": ..., "content": ...} dicts.
            Do NOT include the system prompt — it is built and prepended here.
        profile: The active industry Profile.
        next_field: The FieldSpec application code wants asked about next,
            or None if all required fields are already collected.
    """
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    system_prompt = build_system_prompt(
        profile,
        is_demo=is_demo,
        is_business_hours=is_business_hours,
        business_name=business_name,
        next_field=next_field,
    )
    timeout_seconds = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "10"))

    messages = [{"role": "system", "content": system_prompt}] + conversation_history
    last_user = _last_user_message(conversation_history)

    try:
        response = _get_client().chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=600,
            response_format={"type": "json_object"},
            timeout=timeout_seconds,
        )

        if not getattr(response, "choices", None):
            logger.error("[openai] No choices returned from API.")
            return _fallback(profile, reason="No choices returned from API", conversation_history=conversation_history)

        message = response.choices[0].message
        raw = getattr(message, "content", None)

        if raw is None or not str(raw).strip():
            logger.error("[openai] Empty content returned from API.")
            return _fallback(profile, reason="Empty content returned from API", conversation_history=conversation_history)

        logger.debug(f"[openai] Raw response: {raw}")

        data = json.loads(raw)
        valid, error = _validate(data, profile)

        if not valid:
            logger.error(
                "[openai] Validation failed — %s | Last user message: %r | Raw: %s",
                error, last_user, raw,
            )
            return _fallback(profile, reason=f"Validation error: {error}", conversation_history=conversation_history)

        return _normalize(data, profile)

    except json.JSONDecodeError as e:
        logger.error("[openai] JSON decode error: %s | Last user message: %r", e, last_user)
        return _fallback(profile, reason=f"JSON decode error: {e}", conversation_history=conversation_history)

    except Exception as e:
        logger.exception("[openai] Unexpected error during OpenAI call | Last user message: %r", last_user)
        return _fallback(profile, reason=str(e), conversation_history=conversation_history)


def _fallback(profile: Profile, reason: str, conversation_history: list[dict] | None = None) -> dict:
    """
    Safe response used when OpenAI returns something invalid or fails
    entirely. Always terminates the session to prevent an uncontrolled loop.
    """
    last_user = _last_user_message(conversation_history or [])
    logger.error("[openai] Using fallback | reason=%s | last_user=%r", reason, last_user)

    return {
        "reply": (
            "Sorry, we ran into an issue on our end. The team will follow "
            "up with you directly. Thanks for your patience!"
        ),
        "category": "unknown" if "unknown" in profile.categories else profile.categories[-1],
        "extracted_fields": {f.key: None for f in profile.fields},
        "is_complete": False,
        "business_summary": "AI failure — fallback triggered.",
        "topic_status": "on_topic",
        "should_terminate": True,
        "termination_reason": "error",
    }
