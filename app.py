"""
app.py
SMS Intake Assistant — Flask entry point.

Routes:
  POST /sms    — Twilio inbound SMS webhook (main intake flow)
  POST /reset  — Clear one or all sessions (development/testing)
  GET  /health — Liveness check

Fixes applied:
  - Rate limiter keyed on Twilio "From" phone number, not IP address
  - All outbound replies (AI, greeting, max-turns, fallback) pass through
    _safe_reply(), which enforces the MAX_REPLY_LENGTH cap uniformly
  - Off-topic strikes reset when user returns to on-topic conversation
  - max_turns fallback category = "unknown"
  - Startup env var check warns on missing required vars (no crash)
"""

import os
import logging
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

load_dotenv()

# ─── Logging setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Startup env var check ────────────────────────────────────────────────────
_REQUIRED_ENV_VARS = [
    "OPENAI_API_KEY",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_PHONE_NUMBER",
    "BUSINESS_NAME",
    "BUSINESS_TYPE",
]

def _check_env_vars() -> None:
    missing = [v for v in _REQUIRED_ENV_VARS if not os.getenv(v, "").strip()]
    if missing:
        for var in missing:
            logger.warning(f"[app] Missing required environment variable: {var}")
        logger.warning(
            "[app] Some required env vars are not set. "
            "The app will start but may behave incorrectly."
        )

_check_env_vars()

# ─── Flask setup ──────────────────────────────────────────────────────────────
app = Flask(__name__)

# Rate limit keyed on the Twilio "From" phone number.
# Falls back to IP if "From" is not present (e.g. health checks).
def _rate_limit_key() -> str:
    return request.form.get("From") or get_remote_address()

limiter = Limiter(
    _rate_limit_key,
    app=app,
    default_limits=[],       # No blanket limit — applied per-route only
    storage_uri="memory://",
)

# ─── Module imports after load_dotenv so env vars are available ───────────────
from modules import conversation, openai_helper, sheets_helper, twilio_helper
from modules.business_hours import get_greeting

# ─── Constants ────────────────────────────────────────────────────────────────
# All outbound SMS replies are truncated to this length, without exception.
MAX_REPLY_LENGTH = 500

MAX_TURNS_REPLY = (
    "We've reached the limit of what we can collect over text. "
    "The team will follow up with you directly — thanks!"
)


# ─────────────────────────────────────────────────────────────────────────────
# /sms  — main Twilio webhook
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/sms", methods=["POST"])
@limiter.limit("10 per minute")
def sms_intake():
    """
    Receives inbound SMS from Twilio and drives the intake conversation.

    Flow:
      1.  Validate Twilio webhook signature (prod only)
      2.  Extract phone number + message body
      3.  New session  → send greeting, return early
      4.  Terminated   → ignore silently (204)
      5.  Max turns    → close gracefully, log lead
      6.  Add user message → call OpenAI → validate response
      7.  Merge extracted fields into session state
      8.  Track off-topic strikes / reset on recovery
      9.  If should_terminate → log lead → mark session closed
      10. Return reply via _safe_reply() (truncation applied here)
    """

    # 1. Signature validation (skipped in development)
    twilio_helper.validate_twilio_request()

    # 2. Extract inbound data
    phone = request.form.get("From", "").strip()
    body  = request.form.get("Body", "").strip()

    if not phone or not body:
        logger.warning("[app] Received request with missing From or Body.")
        return "", 400

    logger.info(f"[app] Inbound from {phone}: {body!r}")

    # 3. New session → greeting
    if not conversation.session_exists(phone):
        conversation.get_session(phone)          # initialise
        greeting = get_greeting()
        conversation.add_assistant_message(phone, greeting)
        logger.info(f"[app] Greeting sent to {phone}")
        return _safe_reply(greeting)

    # 4. Already terminated → no reply
    if conversation.is_terminated(phone):
        logger.info(f"[app] Message from closed session {phone} — ignored.")
        return "", 204

    # 5. Max turns → close gracefully
    if conversation.is_at_max_turns(phone):
        logger.warning(f"[app] Max turns reached for {phone}")
        conversation.mark_terminated(phone)
        _log_lead(phone, {
            "category": "unknown",
            "topic_status": "on_topic",
            "termination_reason": "max_turns",
            "is_complete": False,
            "business_summary": "Conversation reached the maximum turn limit.",
        })
        return _safe_reply(MAX_TURNS_REPLY)

    # 6. Add user message → AI response
    conversation.add_user_message(phone, body)
    history   = conversation.get_history(phone)
    ai_result = openai_helper.get_ai_response(history)

    # 7. Merge extracted fields (never lose earlier data)
    conversation.merge_fields(phone, ai_result.get("extracted_fields", {}))

    # 8. Off-topic tracking / reset on recovery
    topic_status = ai_result.get("topic_status", "on_topic")
    if topic_status == "off_topic":
        strikes = conversation.increment_off_topic(phone)
        logger.info(f"[app] Off-topic strike {strikes} for {phone}")
    elif topic_status == "on_topic":
        conversation.reset_off_topic_strikes(phone)

    # 9. Terminate if AI says so
    reply_text = ai_result["reply"]
    if ai_result.get("should_terminate"):
        reason = ai_result.get("termination_reason", "completed")
        logger.info(f"[app] Terminating {phone} — reason: {reason}")
        conversation.add_assistant_message(phone, reply_text)
        conversation.mark_terminated(phone)
        _log_lead(phone, ai_result)
    else:
        conversation.add_assistant_message(phone, reply_text)

    # 10. Reply — truncation applied inside _safe_reply()
    return _safe_reply(reply_text)


# ─────────────────────────────────────────────────────────────────────────────
# /reset  — testing helper
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/reset", methods=["POST"])
def reset():
    """
    Clears one or all in-memory sessions.

    Body (JSON or form):
      phone : number to reset (optional — omit to clear everything)

    Returns JSON confirmation.
    """
    data  = request.get_json(silent=True) or request.form
    phone = (data.get("phone", "") or "").strip()

    if phone:
        conversation.reset_session(phone)
        return jsonify({"status": "ok", "cleared": phone}), 200

    count = conversation.reset_all_sessions()
    return jsonify({"status": "ok", "cleared": f"{count} session(s)"}), 200


# ─────────────────────────────────────────────────────────────────────────────
# /health
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "sms-intake-assistant"}), 200


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _safe_reply(message: str):
    """
    Truncates message to MAX_REPLY_LENGTH, then wraps in TwiML.
    Every outbound SMS reply — AI, greeting, max-turns, fallback — goes
    through here so the length cap is enforced uniformly in one place.
    """
    xml = twilio_helper.build_twiml_response(message[:MAX_REPLY_LENGTH])
    return xml, 200, {"Content-Type": "text/xml"}


def _log_lead(phone: str, ai_result: dict) -> None:
    """Convenience wrapper — pulls session and calls sheets_helper."""
    session = conversation.get_session(phone)
    sheets_helper.log_lead(phone, session, ai_result)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port  = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_ENV", "development").lower() == "development"
    logger.info(f"[app] Starting on port {port} (debug={debug})")
    app.run(host="0.0.0.0", port=port, debug=debug)
