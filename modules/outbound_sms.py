"""Small, provider-boundary helper for transactional outbound SMS."""

from __future__ import annotations

import os

from twilio.rest import Client


class OutboundSMSConfigurationError(RuntimeError):
    pass


def send(*, to: str, from_phone: str, body: str) -> str:
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    if not account_sid or not auth_token:
        raise OutboundSMSConfigurationError("Twilio credentials are not configured.")
    message = Client(account_sid, auth_token).messages.create(
        to=to,
        from_=from_phone,
        body=body,
    )
    sid = str(getattr(message, "sid", "") or "")
    if not sid:
        raise RuntimeError("Twilio did not return a message ID.")
    return sid
