"""
app.py
SMS Intake Assistant -- Flask entry point.

Routes:
  POST /sms    - Twilio inbound SMS webhook (main intake flow)
  POST /reset  - Clear one or all sessions (development/testing)
  GET  /health - Liveness check

Supports two modes (see modules/app_mode.py):
  APP_MODE=demo       - NTX Automation Co. multi-industry demo, menu-driven.
  APP_MODE=production - locked to a single client profile (DEFAULT_PROFILE).

State is persisted in PostgreSQL/SQLite via modules/conversation_store.py --
nothing customer-facing lives only in process memory, so a restart never
loses an active conversation.
"""

import os
import logging
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

load_dotenv()

# --- Logging setup -------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# --- App-mode boundary: fails loudly at startup on misconfiguration ------
from modules.app_mode import validate_startup, AppModeConfigError

try:
    APP_CONFIG = validate_startup()
except AppModeConfigError as e:
    logger.error(f"[app] FATAL startup configuration error: {e}")
    raise

# --- Startup env var check (warns, does not crash) ------------------------
_REQUIRED_ENV_VARS = ["OPENAI_API_KEY", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"]


def _check_env_vars() -> None:
    missing = [v for v in _REQUIRED_ENV_VARS if not os.getenv(v, "").strip()]
    if missing:
        for var in missing:
            logger.warning(f"[app] Missing required environment variable: {var}")
        logger.warning("[app] Some required env vars are not set. The app will start but may behave incorrectly.")


_check_env_vars()

# --- Module imports (after load_dotenv so env vars are available) --------
from modules import conversation_store, compliance, conversation_policy, intake_engine, menu_text, missed_call, openai_helper, sheets_helper, twilio_helper
from modules.business_hours import get_greeting, is_business_hours
from modules.profiles import PROFILES, match_menu_selection
from modules.db import init_db, session_scope, get_database_url, is_sqlite

# --- Database setup --------------------------------------------------------
_db_url = get_database_url()
if is_sqlite(_db_url):
    logger.info(f"[app] Using SQLite ({_db_url}) -- dev/test only. Auto-creating tables.")
    init_db()
else:
    logger.info("[app] Using external database. Run `alembic upgrade head` to apply migrations.")

# --- Flask setup -------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "")
if not app.config["SECRET_KEY"]:
    logger.warning("[app] SECRET_KEY is not set. Set it before deploying to production.")


def _rate_limit_key() -> str:
    return request.form.get("From") or get_remote_address()


limiter = Limiter(
    _rate_limit_key,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

MAX_REPLY_LENGTH = 500

ENABLED_PROFILES = [PROFILES[k] for k in APP_CONFIG.enabled_profile_keys]
MID_FLOW_RESET_KEYWORDS = {"MENU", "DEMO"}  # START is handled as a compliance keyword


def _business_name() -> str:
    return "NTX Automation Co." if APP_CONFIG.is_demo else os.getenv("BUSINESS_NAME", "our business")


def _max_turns_reply() -> str:
    return menu_text.MAX_TURNS_REPLY_DEMO if APP_CONFIG.is_demo else menu_text.MAX_TURNS_REPLY_PRODUCTION


def _voice_twiml(message_sent: bool) -> str:
    """Returns a short, valid Voice response without exposing internal rules."""
    if message_sent:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response><Say>Thanks for calling. We'll text you shortly.</Say><Hangup/></Response>"
        )
    return '<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>'


# -----------------------------------------------------------------------------
# /sms -- main Twilio webhook
# -----------------------------------------------------------------------------

@app.route("/sms", methods=["POST"])
@limiter.limit("10 per minute")
def sms_intake():
    twilio_helper.validate_twilio_request()

    phone = request.form.get("From", "").strip()
    body = request.form.get("Body", "").strip()
    message_sid = request.form.get("MessageSid", "").strip()

    if not phone or not body:
        logger.warning("[app] Received request with missing From or Body.")
        return "", 400

    logger.info(f"[app] Inbound from {phone}: {len(body)} chars")

    try:
        db = session_scope()
    except Exception:
        logger.exception("[app] Database connection failure.")
        return "", 500

    try:
        return _handle_sms(db, phone, body, message_sid)
    except Exception:
        logger.exception(f"[app] Unhandled error processing message from {phone}.")
        xml = twilio_helper.build_twiml_response(
            "Sorry, we ran into an issue on our end. The team will follow up with you directly."
        )
        return xml, 200, {"Content-Type": "text/xml"}
    finally:
        db.close()


def _handle_sms(db, phone: str, body: str, message_sid: str):
    # --- Idempotency: replay identical response for a retried MessageSid ---
    existing = conversation_store.find_processed_message(db, message_sid)
    if existing is not None:
        logger.info(f"[app] Duplicate MessageSid {message_sid} -- replaying prior response.")
        if not existing.response_body:
            return "", 204
        return existing.response_body, 200, {"Content-Type": "text/xml"}

    session, is_new = conversation_store.get_or_create_session(
        db, phone,
        is_demo=APP_CONFIG.is_demo,
        default_profile_key=APP_CONFIG.default_profile_key,
    )

    # --- Compliance keywords: processed before menu logic or the LLM -------
    classification = compliance.classify(body)

    if classification == "stop":
        conversation_store.mark_opted_out(db, session, True)
        return _finalize(db, phone, message_sid, compliance.STOP_REPLY)

    if session.opted_out and classification != "start":
        conversation_store.record_processed_message(db, message_sid, phone, "")
        return "", 204

    if classification == "start":
        conversation_store.mark_opted_out(db, session, False)
        if APP_CONFIG.is_demo:
            conversation_store.reset_to_menu(db, session)
            reply = f"{compliance.START_REPLY_DEMO} {menu_text.build_menu_text(ENABLED_PROFILES)}"
        else:
            conversation_store.set_profile(db, session, APP_CONFIG.default_profile_key)
            reply = get_greeting()
        return _finalize(db, phone, message_sid, reply)

    if classification == "help":
        return _finalize(db, phone, message_sid, compliance.HELP_REPLY)

    # Keep a recently completed intake available for natural follow-up instead
    # of treating the next text as a brand-new customer. MENU still starts a
    # fresh demo explicitly, and TTL expiry eventually clears the session.
    if session.terminated:
        if APP_CONFIG.is_demo and body.strip().upper() in MID_FLOW_RESET_KEYWORDS:
            conversation_store.reset_to_menu(db, session)
            reply = menu_text.build_menu_text(ENABLED_PROFILES)
        else:
            reply = menu_text.build_completed_followup_text(body, APP_CONFIG.is_demo)
        conversation_store.add_assistant_message(db, session, reply)
        conversation_store.touch(db, session)
        return _finalize(db, phone, message_sid, reply)

    # --- Brand-new session: greeting / menu, no LLM call yet ---------------
    if is_new:
        if APP_CONFIG.is_demo:
            reply = menu_text.build_menu_text(ENABLED_PROFILES)
        else:
            reply = get_greeting()
        conversation_store.add_assistant_message(db, session, reply)
        conversation_store.touch(db, session)
        return _finalize(db, phone, message_sid, reply)

    # --- Demo: still selecting an industry -----------------------------------
    if APP_CONFIG.is_demo and session.state == "awaiting_profile_selection":
        if body.strip().upper() in MID_FLOW_RESET_KEYWORDS:
            reply = menu_text.build_menu_text(ENABLED_PROFILES)
            conversation_store.add_assistant_message(db, session, reply)
            conversation_store.touch(db, session)
            return _finalize(db, phone, message_sid, reply)

        profile_key = match_menu_selection(body)
        if profile_key and profile_key in APP_CONFIG.enabled_profile_keys:
            conversation_store.set_profile(db, session, profile_key)
            profile = PROFILES[profile_key]
            first_field = intake_engine.next_missing_field(profile, {})
            reply = menu_text.build_profile_intro(profile, first_field)
        else:
            reply = menu_text.build_invalid_selection_text(ENABLED_PROFILES)

        conversation_store.add_assistant_message(db, session, reply)
        conversation_store.touch(db, session)
        return _finalize(db, phone, message_sid, reply)

    # --- Mid-flow MENU/DEMO reset (demo mode only) --------------------------
    if APP_CONFIG.is_demo and body.strip().upper() in MID_FLOW_RESET_KEYWORDS:
        conversation_store.reset_to_menu(db, session)
        reply = menu_text.build_menu_text(ENABLED_PROFILES)
        conversation_store.add_assistant_message(db, session, reply)
        conversation_store.touch(db, session)
        return _finalize(db, phone, message_sid, reply)

    # --- Normal in-progress intake turn --------------------------------------
    profile = PROFILES[session.profile_key]

    if conversation_store.is_at_max_turns(session):
        logger.warning(f"[app] Max turns reached for {phone}")
        reply = _max_turns_reply()
        conversation_store.add_assistant_message(db, session, reply)
        conversation_store.mark_terminated(db, session)
        ai_result = {
            "category": None,
            "topic_status": "on_topic",
            "termination_reason": "max_turns",
            "is_complete": False,
            "business_summary": "Conversation reached the maximum turn limit.",
        }
        conversation_store.record_lead(db, session, ai_result, status="escalated")
        _export_to_sheets(profile, session, ai_result)
        return _finalize(db, phone, message_sid, reply)

    conversation_store.add_user_message(db, session, body)
    next_field = intake_engine.next_missing_field(profile, session.fields)

    pending_vehicle = conversation_store.get_pending_vehicle_confirmation(session)
    if pending_vehicle:
        answer = body.strip().lower()
        if answer in {"yes", "yeah", "yep", "correct", "that's right", "that is right"}:
            conversation_store.merge_fields(db, session, pending_vehicle, allowed_keys=set(profile.field_keys()))
            conversation_store.clear_pending_vehicle_confirmation(db, session)
            remaining_field = intake_engine.next_missing_field(profile, session.fields)
            vehicle = " ".join(pending_vehicle[key] for key in ("vehicle_year", "vehicle_make", "vehicle_model"))
            reply_text = f"Thanks for confirming — a {vehicle}."
            if remaining_field is not None:
                reply_text = f"{reply_text} {remaining_field.question}"
        elif answer in {"no", "nope", "nah"}:
            conversation_store.clear_pending_vehicle_confirmation(db, session)
            reply_text = "No problem. What are the correct year, make or brand, and model?"
        else:
            vehicle = " ".join(pending_vehicle[key] for key in ("vehicle_year", "vehicle_make", "vehicle_model"))
            reply_text = f"Just to confirm, is that a {vehicle}? Reply YES or send the corrected year, make, and model."
        conversation_store.add_assistant_message(db, session, reply_text)
        conversation_store.touch(db, session)
        return _finalize(db, phone, message_sid, reply_text)

    # A normal repair customer often answers the first vehicle question with
    # all three details at once ("2005 Chevy Cobalt LS"). Handle that common
    # structured format before the LLM so the next reply cannot ask for the
    # year again after it was already supplied.
    combined_vehicle_fields = intake_engine.extract_combined_vehicle_details(
        profile,
        body,
        expected_field_key=next_field.key if next_field else None,
    )
    if combined_vehicle_fields:
        conversation_store.merge_fields(
            db,
            session,
            combined_vehicle_fields,
            allowed_keys=set(profile.field_keys()),
        )
        remaining_field = intake_engine.next_missing_field(profile, session.fields)
        vehicle = " ".join(
            combined_vehicle_fields[key]
            for key in ("vehicle_year", "vehicle_make", "vehicle_model")
        )
        reply_text = f"Got it, a {vehicle}."
        if remaining_field is not None:
            reply_text = f"{reply_text} {remaining_field.question}"
        conversation_store.add_assistant_message(db, session, reply_text)
        conversation_store.touch(db, session)
        return _finalize(db, phone, message_sid, reply_text)

    uncertain_vehicle_fields = intake_engine.infer_uncertain_vehicle_details(
        profile,
        body,
        expected_field_key=next_field.key if next_field else None,
    )
    if uncertain_vehicle_fields:
        conversation_store.set_pending_vehicle_confirmation(db, session, uncertain_vehicle_fields)
        vehicle = " ".join(
            uncertain_vehicle_fields[key]
            for key in ("vehicle_year", "vehicle_make", "vehicle_model")
        )
        reply_text = f"Just to confirm, is that a {vehicle}?"
        conversation_store.add_assistant_message(db, session, reply_text)
        conversation_store.touch(db, session)
        return _finalize(db, phone, message_sid, reply_text)

    ai_result = openai_helper.get_ai_response(
        session.history,
        profile=profile,
        is_demo=APP_CONFIG.is_demo,
        is_business_hours=is_business_hours(),
        business_name=_business_name(),
        next_field=next_field,
    )

    validated_fields = intake_engine.validate_extracted_fields(profile, ai_result.get("extracted_fields", {}))
    conversation_store.merge_fields(db, session, validated_fields, allowed_keys=set(profile.field_keys()))

    topic_status = ai_result.get("topic_status", "on_topic")
    if conversation_policy.is_pricing_question(body):
        # Pricing is a valid lead question, never an off-topic strike.
        topic_status = "on_topic"
        ai_result["topic_status"] = "on_topic"
    if topic_status == "off_topic":
        strikes = conversation_store.increment_off_topic(db, session)
        logger.info(f"[app] Off-topic strike {strikes} for {phone}")
    elif topic_status == "on_topic":
        conversation_store.reset_off_topic_strikes(db, session)

    remaining_field = intake_engine.next_missing_field(profile, session.fields)
    reply_text = conversation_policy.enforce_reply_boundaries(
        customer_message=body,
        model_reply=ai_result["reply"],
        next_field=remaining_field,
    )
    should_terminate = bool(ai_result.get("should_terminate"))
    reason = ai_result.get("termination_reason")

    # The application owns completion in both directions. If the final answer
    # filled every required field, close immediately even when the model forgot
    # to mark the turn complete. This also guarantees a consistent handoff and
    # demo disclaimer instead of ending on a vague acknowledgement.
    intake_complete = intake_engine.is_intake_complete(profile, session.fields)
    if intake_complete and topic_status == "on_topic":
        should_terminate = True
        reason = "completed"
        ai_result["is_complete"] = True
        ai_result["should_terminate"] = True
        ai_result["termination_reason"] = "completed"
        reply_text = menu_text.build_completion_text(profile, session.fields, APP_CONFIG.is_demo)

    # Application code, not the model, has final say over "complete":
    # never let a completion claim through unless every required field is
    # actually present in session state.
    if should_terminate and reason == "completed" and not intake_engine.is_intake_complete(profile, session.fields):
        should_terminate = False
        remaining = intake_engine.next_missing_field(profile, session.fields)
        if remaining is not None:
            reply_text = remaining.question

    if should_terminate and reason == "completed":
        reply_text = menu_text.ensure_demo_disclaimer(reply_text, APP_CONFIG.is_demo)

    if should_terminate:
        logger.info(f"[app] Terminating {phone} -- reason: {reason}")
        conversation_store.add_assistant_message(db, session, reply_text)
        conversation_store.mark_terminated(db, session)
        status = "completed" if reason == "completed" else "escalated"
        conversation_store.record_lead(db, session, ai_result, status=status)
        _export_to_sheets(profile, session, ai_result)
    else:
        conversation_store.add_assistant_message(db, session, reply_text)

    conversation_store.touch(db, session)
    return _finalize(db, phone, message_sid, reply_text)


def _export_to_sheets(profile, session, ai_result: dict) -> None:
    try:
        sheets_helper.log_lead(
            session.phone, profile, dict(session.fields or {}), ai_result,
            {"turn_count": session.turn_count, "off_topic_strikes": session.off_topic_strikes},
        )
    except Exception:
        logger.exception(f"[app] Sheets export raised unexpectedly for {session.phone} -- lead is safe in Postgres.")


def _finalize(db, phone: str, message_sid: str, reply_text: str):
    xml = twilio_helper.build_twiml_response(reply_text[:MAX_REPLY_LENGTH])
    conversation_store.record_processed_message(db, message_sid, phone, xml)
    return xml, 200, {"Content-Type": "text/xml"}


# -----------------------------------------------------------------------------
# /voice/missed-call -- Twilio Voice webhook for conditionally forwarded calls
# -----------------------------------------------------------------------------

@app.route("/voice/missed-call", methods=["POST"])
@limiter.limit("10 per minute")
def missed_call_intake():
    twilio_helper.validate_twilio_request()

    caller_phone = request.form.get("From", "").strip()
    twilio_number = request.form.get("To", "").strip()
    forwarded_from = request.form.get("ForwardedFrom", "").strip()
    call_sid = request.form.get("CallSid", "").strip()

    try:
        db = session_scope()
    except Exception:
        logger.exception("[missed_call] Database connection failure.")
        return _voice_twiml(False), 200, {"Content-Type": "text/xml"}

    try:
        outcome = missed_call.process_missed_call(
            db,
            caller_phone=caller_phone,
            twilio_number=twilio_number,
            forwarded_from=forwarded_from,
            call_sid=call_sid,
            business_name=_business_name(),
            is_demo=APP_CONFIG.is_demo,
        )
        return _voice_twiml(outcome.message_sent), 200, {"Content-Type": "text/xml"}
    except Exception:
        logger.exception("[missed_call] Unhandled error processing CallSid=%s.", call_sid or "missing")
        return _voice_twiml(False), 200, {"Content-Type": "text/xml"}
    finally:
        db.close()


# -----------------------------------------------------------------------------
# /reset -- testing helper
# -----------------------------------------------------------------------------

@app.route("/reset", methods=["POST"])
def reset():
    data = request.get_json(silent=True) or request.form
    phone = (data.get("phone", "") or "").strip()

    db = session_scope()
    try:
        if phone:
            cleared = conversation_store.reset_session(db, phone)
            return jsonify({"status": "ok", "cleared": phone if cleared else None}), 200

        count = conversation_store.reset_all_sessions(db)
        return jsonify({"status": "ok", "cleared": f"{count} session(s)"}), 200
    finally:
        db.close()


# -----------------------------------------------------------------------------
# /health
# -----------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "sms-intake-assistant", "mode": APP_CONFIG.mode}), 200


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_ENV", "development").lower() == "development"
    logger.info(f"[app] Starting on port {port} (debug={debug}, mode={APP_CONFIG.mode})")
    app.run(host="0.0.0.0", port=port, debug=debug)
