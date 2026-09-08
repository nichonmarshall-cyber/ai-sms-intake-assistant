"""Password hashing.

Unlike session tokens, passwords are low-entropy and human-chosen, so they get
a deliberately slow KDF (Werkzeug's scrypt).
"""

from __future__ import annotations

from werkzeug.security import check_password_hash, generate_password_hash


# A real scrypt hash of a value nobody can log in with. Verifying against this
# when an email does not exist keeps failed-login timing roughly constant, so
# response time cannot be used to enumerate registered accounts.
DUMMY_HASH = generate_password_hash("ntx-nonexistent-account-placeholder")

MIN_PASSWORD_LENGTH = 12


def hash_password(password: str) -> str:
    return generate_password_hash(password, method="scrypt")


def verify_password(stored_hash: str | None, password: str) -> bool:
    return check_password_hash(stored_hash or DUMMY_HASH, password or "")


def burn_dummy_verification(password: str) -> None:
    """Spends the same work as a real check when the account does not exist."""
    check_password_hash(DUMMY_HASH, password or "")


def validate_password_strength(password: str) -> str | None:
    """Returns an error message, or None when acceptable."""
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    return None
