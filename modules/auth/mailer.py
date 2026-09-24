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
    if not configured():
        logger.warning("[auth] Password reset requested but SMTP is not configured.")
        return False

    base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        logger.warning("[auth] Password reset requested but PUBLIC_BASE_URL is not configured.")
        return False
    if os.getenv("FLASK_ENV", "development").strip().lower() == "production" and not base_url.startswith("https://"):
        logger.error("[auth] Refusing to send a production reset link over a non-HTTPS base URL.")
        return False
    link = f"{base_url}/reset-password?{urlencode({'token': token})}"

    message = EmailMessage()
    message["Subject"] = "Reset your NTX dashboard password"
    message["From"] = os.environ["SMTP_FROM_EMAIL"].strip()
    message["To"] = recipient
    message.set_content(
        "Use the secure link below to reset your NTX Automation Co. dashboard password. "
        "The link expires in 30 minutes and works once.\n\n"
        f"{link}\n\nIf you did not request this, you can ignore this email."
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
        logger.exception("[auth] SMTP password reset delivery failed.")
        return False
