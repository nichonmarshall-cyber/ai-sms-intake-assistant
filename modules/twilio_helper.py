"""
twilio_helper.py
Two responsibilities:

1. validate_twilio_request()
   Validates that an inbound POST genuinely came from Twilio.
   Behaviour is controlled by FLASK_ENV:
     - development  → validation skipped, warning logged
     - production   → validation enforced, 403 on failure

2. build_twiml_response(message)
   Wraps a plain-text message in the minimal TwiML XML Twilio expects
   for an SMS reply.
"""

import os
import logging
from flask import request, abort
from twilio.request_validator import RequestValidator

logger = logging.getLogger(__name__)


def validate_twilio_request() -> None:
    """
    Call this at the top of the /sms route handler.

    Production:   aborts with 403 if the Twilio signature is invalid.
    Development:  logs a warning and continues (never use in prod).
    """
    env = os.getenv("FLASK_ENV", "development").lower()

    if env != "production":
        logger.warning(
            "[twilio] Webhook validation SKIPPED — FLASK_ENV is not 'production'. "
            "Set FLASK_ENV=production before going live."
        )
        return

    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
    if not auth_token:
        logger.error("[twilio] TWILIO_AUTH_TOKEN is not set. Cannot validate.")
        abort(500, description="Server misconfiguration: missing TWILIO_AUTH_TOKEN.")

    validator  = RequestValidator(auth_token)
    signature  = request.headers.get("X-Twilio-Signature", "")
    post_vars  = request.form.to_dict()

    if not validator.validate(request.url, post_vars, signature):
        logger.warning(f"[twilio] Invalid signature from {request.remote_addr}")
        abort(403, description="Forbidden: invalid Twilio webhook signature.")


def build_twiml_response(message: str) -> str:
    """
    Returns a minimal TwiML XML string for an SMS reply.

    Special XML characters in the message are escaped to prevent
    malformed TwiML responses.
    """
    safe = (
        message
        .replace("&",  "&amp;")
        .replace("<",  "&lt;")
        .replace(">",  "&gt;")
        .replace('"',  "&quot;")
        .replace("'",  "&apos;")
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Message>{safe}</Message></Response>"
    )
