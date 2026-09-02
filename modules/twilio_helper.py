"""
twilio_helper.py
Two responsibilities:

1. validate_twilio_request()
   Validates that an inbound POST genuinely came from Twilio, using the
   X-Twilio-Signature header.

   Bypass is controlled ONLY by the explicit TWILIO_VALIDATION_BYPASS=true
   environment variable (development/testing use only). A startup guard in
   modules/app_mode.py refuses to start the process at all if this bypass
   is enabled while APP_MODE=production or FLASK_ENV=production, so it
   cannot leak into a live deployment.

2. build_twiml_response(message)
   Wraps a plain-text message in the minimal TwiML XML Twilio expects
   for an SMS reply.
"""

import os
import logging
from flask import request, abort
from twilio.request_validator import RequestValidator

logger = logging.getLogger(__name__)


def _webhook_url() -> str:
    """
    Reconstructs the exact URL Twilio POSTed to, for signature validation.

    Prefers PUBLIC_BASE_URL (the HTTPS URL configured in Twilio) over
    request.url, because request.url reflects whatever scheme/host Flask
    sees — which is http:// and an internal hostname when running behind
    Render's reverse proxy, and would never match Twilio's signature.
    """
    base = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not base:
        return request.url

    qs = request.query_string.decode() if request.query_string else ""
    return f"{base}{request.path}" + (f"?{qs}" if qs else "")


def validate_twilio_request() -> None:
    """Call this at the top of the /sms route handler."""
    bypass = os.getenv("TWILIO_VALIDATION_BYPASS", "false").strip().lower() == "true"
    if bypass:
        logger.warning(
            "[twilio] Signature validation BYPASSED via TWILIO_VALIDATION_BYPASS=true. "
            "This must never be enabled in production."
        )
        return

    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
    if not auth_token:
        logger.error("[twilio] TWILIO_AUTH_TOKEN is not set. Cannot validate.")
        abort(500, description="Server misconfiguration: missing TWILIO_AUTH_TOKEN.")

    validator = RequestValidator(auth_token)
    signature = request.headers.get("X-Twilio-Signature", "")
    post_vars = request.form.to_dict()
    url = _webhook_url()

    if not validator.validate(url, post_vars, signature):
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
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Message>{safe}</Message></Response>"
    )
