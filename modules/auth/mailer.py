"""Small SMTP adapter for transactional account email."""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


def configured() -> bool:
    return bool(os.getenv("SMTP_HOST", "").strip() and os.getenv("SMTP_FROM_EMAIL", "").strip())


def send_password_reset(*, recipient: str, token: str) -> bool:
    return _send_password_link(recipient=recipient, token=token, setup=False)


def send_account_setup(*, recipient: str, token: str) -> bool:
    return _send_password_link(recipient=recipient, token=token, setup=True)


def _send_password_link(*, recipient: str, token: str, setup: bool) -> bool:
    purpose = "Account setup" if setup else "Password reset"
    if not configured():
        logger.warning("[auth] %s requested but SMTP is not configured.", purpose)
        return False

    base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        logger.warning("[auth] %s requested but PUBLIC_BASE_URL is not configured.", purpose)
        return False
    if os.getenv("FLASK_ENV", "development").strip().lower() == "production" and not base_url.startswith("https://"):
        logger.error("[auth] Refusing to send a production %s link over a non-HTTPS base URL.", purpose.lower())
        return False
    query = {"token": token}
    if setup:
        query["setup"] = "1"
    link = f"{base_url}/reset-password?{urlencode(query)}"

    message = EmailMessage()
    message["Subject"] = (
        "Set up your NTX dashboard account" if setup else "Reset your NTX dashboard password"
    )
    message["From"] = os.environ["SMTP_FROM_EMAIL"].strip()
    message["To"] = recipient
    intro = (
        "You have been invited to the NTX Automation Co. dashboard. Use the secure link "
        "below to choose your password. "
        if setup
        else "Use the secure link below to reset your NTX Automation Co. dashboard password. "
    )
    message.set_content(
        intro + "The link expires in 30 minutes and works once.\n\n"
        f"{link}\n\nIf you did not expect this email, you can ignore it."
    )

    try:
        host = os.environ["SMTP_HOST"].strip()
        port = int(os.getenv("SMTP_PORT", "587"))
        username = os.getenv("SMTP_USERNAME", "").strip()
        password = os.getenv("SMTP_PASSWORD", "")
        use_tls = os.getenv("SMTP_USE_TLS", "true").strip().lower() in {"1", "true", "yes", "on"}
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            if use_tls:
                smtp.starttls()
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
        return True
    except Exception:
        logger.exception("[auth] SMTP %s delivery failed.", purpose.lower())
        return False
