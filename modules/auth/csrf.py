"""Double-submit CSRF, bound to the authenticated database session.

The readable cookie alone is not trusted: the presented header token is hashed
and compared in constant time against ``user_sessions.csrf_hash``, so a token
minted for one session cannot be replayed against another.

Twilio webhooks are exempt -- Twilio cannot send a custom header, and those
routes are already authenticated by X-Twilio-Signature validation.
"""

from __future__ import annotations

CSRF_HEADER = "X-CSRF-Token"

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Paths that must never require a CSRF header. These are Twilio-facing or
# token-authenticated and are protected by their own mechanisms.
EXEMPT_PATHS = frozenset({"/sms", "/voice/missed-call", "/health", "/reset"})


def is_exempt(path: str, method: str) -> bool:
    if method.upper() in SAFE_METHODS:
        return True
    return path.rstrip("/") in EXEMPT_PATHS or path in EXEMPT_PATHS
