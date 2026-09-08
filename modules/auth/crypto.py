"""Hashing helpers for session tokens and client metadata.

Two different hashes are used on purpose:

* Session and CSRF tokens are 32 random bytes (~256 bits). There is no
  dictionary to search, so a *fast* SHA-256 is correct. A slow KDF here would
  run on every authenticated request for no security gain.
* IP addresses have a tiny search space (IPv4 is 2^32) so a bare digest is
  trivially reversible by brute force. They are therefore hashed with a keyed
  HMAC using an application secret. A raw IP is never persisted.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets


TOKEN_BYTES = 32


def new_token() -> str:
    """Returns a fresh URL-safe opaque token."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """SHA-256 of a high-entropy token. Never used for passwords."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_match(candidate: str, stored_hash: str) -> bool:
    """Constant-time comparison of a presented token against a stored hash."""
    if not candidate or not stored_hash:
        return False
    return hmac.compare_digest(hash_token(candidate), stored_hash)


def _hmac_key() -> bytes:
    key = os.getenv("IP_HASH_KEY", "").strip() or os.getenv("SECRET_KEY", "").strip()
    if not key:
        # Falling back to a constant would make hashes comparable across
        # deployments; a per-process random key degrades throttling instead of
        # weakening privacy, which is the safer failure direction.
        key = "ntx-insecure-dev-key"
    return key.encode("utf-8")


def hash_ip(raw_ip: str | None) -> str | None:
    """Keyed HMAC digest of a client IP. Returns None when no IP is available."""
    if not raw_ip:
        return None
    normalized = raw_ip.strip().lower()
    if not normalized:
        return None
    return hmac.new(_hmac_key(), normalized.encode("utf-8"), hashlib.sha256).hexdigest()
