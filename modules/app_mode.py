"""
app_mode.py
Resolves and validates the APP_MODE boundary between the multi-industry
demo and a single-client production deployment.

APP_MODE=demo         - shows the NTX Automation Co. industry menu, allows
                        switching industries with MENU, never claims a real
                        booking happened.
APP_MODE=production   - locked to exactly one profile (DEFAULT_PROFILE).
                        Never shows the demo menu.

The mode is resolved once at process startup (see validate_startup()) and
is never influenced by conversation content — only by the environment.
"""

import os
import logging

from modules.profiles import PROFILES, resolve_profile_key, get_enabled_profiles

logger = logging.getLogger(__name__)

VALID_MODES = {"demo", "production"}


class AppModeConfigError(RuntimeError):
    """Raised when the environment is misconfigured for the selected APP_MODE."""


def get_app_mode() -> str:
    raw = os.getenv("APP_MODE", "demo").strip().lower()
    if raw not in VALID_MODES:
        raise AppModeConfigError(
            f"APP_MODE must be one of {sorted(VALID_MODES)}, got: '{raw}'"
        )
    return raw


def get_default_profile_key() -> str:
    """
    Production-mode only. Raises AppModeConfigError if DEFAULT_PROFILE is
    missing or does not resolve to a known profile.
    """
    raw = os.getenv("DEFAULT_PROFILE", "").strip()
    if not raw:
        raise AppModeConfigError(
            "APP_MODE=production requires DEFAULT_PROFILE to be set to one of: "
            f"{sorted(PROFILES.keys())}"
        )
    key = resolve_profile_key(raw)
    if key is None:
        raise AppModeConfigError(
            f"DEFAULT_PROFILE='{raw}' is not a recognized profile. "
            f"Valid options: {sorted(PROFILES.keys())}"
        )
    return key


def get_enabled_profile_keys() -> list[str]:
    raw = os.getenv("ENABLED_PROFILES", "").strip()
    if not raw:
        return [p.key for p in get_enabled_profiles(None)]
    return [p.key for p in get_enabled_profiles(raw.split(","))]


def _validate_signature_bypass_guard(mode: str) -> None:
    """
    FLASK_ENV=production is the deployment-environment signal (are we
    actually running on live infrastructure?) and is deliberately checked
    here instead of APP_MODE. APP_MODE=production only selects single-client
    business logic and may still be exercised locally/in CI with the bypass
    on; a real deployed process must never bypass signature validation
    regardless of which APP_MODE it's running.
    """
    bypass = os.getenv("TWILIO_VALIDATION_BYPASS", "false").strip().lower() == "true"
    flask_env = os.getenv("FLASK_ENV", "development").strip().lower()

    if bypass and flask_env == "production":
        raise AppModeConfigError(
            "TWILIO_VALIDATION_BYPASS=true is not allowed when FLASK_ENV=production. "
            "Twilio signature validation must be enforced in every real deployment."
        )


class AppConfig:
    """Resolved, validated configuration for the running process."""

    def __init__(self, mode: str, default_profile_key: str | None, enabled_profile_keys: list[str]):
        self.mode = mode
        self.default_profile_key = default_profile_key
        self.enabled_profile_keys = enabled_profile_keys

    @property
    def is_demo(self) -> bool:
        return self.mode == "demo"

    @property
    def is_production(self) -> bool:
        return self.mode == "production"


def validate_startup() -> AppConfig:
    """
    Called once at app startup. Fails loudly (raises AppModeConfigError) if
    the environment is invalid for the selected mode, so misconfiguration
    is caught before the process starts serving traffic.
    """
    mode = get_app_mode()
    _validate_signature_bypass_guard(mode)

    if mode == "production":
        default_key = get_default_profile_key()
        logger.info(f"[app_mode] APP_MODE=production, DEFAULT_PROFILE={default_key}")
        return AppConfig(mode=mode, default_profile_key=default_key, enabled_profile_keys=[default_key])

    enabled = get_enabled_profile_keys()
    logger.info(f"[app_mode] APP_MODE=demo, ENABLED_PROFILES={enabled}")
    return AppConfig(mode=mode, default_profile_key=None, enabled_profile_keys=enabled)
