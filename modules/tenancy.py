"""Multi-business routing and rule inheritance.

The inbound Twilio ``To`` number is the tenant boundary.  A client never
supplies a business ID in an SMS; the platform resolves it from that number,
then scopes every session, lead, and missed-call event to the resolved tenant.

Rules are layered deliberately:
    platform defaults -> business settings -> phone/location exceptions

This lets NTX keep safe global behavior while a business can configure its own
hours, allowed intake profiles, follow-up copy, and per-location exceptions.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from modules.conversation_store import normalize_phone
from modules.models import AuditEvent, Business, BusinessPhoneNumber
from modules.profiles import PROFILES, resolve_profile_key


LEGACY_BUSINESS_ID = "legacy-demo"


DEFAULT_BUSINESS_SETTINGS = {
    "intake": {
        "enabled_profiles": [],
        "default_profile_key": None,
        "selection_mode": "single",
        "demo_disclaimer": False,
    },
    "missed_calls": {
        "enabled": False,
        "cooldown_minutes": 1440,
        "require_allowlist": False,
        "allowlist": [],
        "blocklist": [],
    },
    "business_hours": {
        "timezone": "America/Chicago",
        "open_hour": 8,
        "close_hour": 17,
        "workdays": [0, 1, 2, 3, 4],
    },
}


@dataclass(frozen=True)
class TenantContext:
    business: Business
    phone_number: BusinessPhoneNumber
    settings: dict


@dataclass(frozen=True)
class RuntimeTenant:
    """Validated request-scoped configuration used by SMS and Voice routes."""

    business_id: str | None
    business_name: str
    enabled_profile_keys: tuple[str, ...]
    default_profile_key: str | None
    show_profile_menu: bool
    is_demo: bool
    settings: dict


class TenantConfigError(ValueError):
    pass


def _deep_merge(base: dict, override: dict | None) -> dict:
    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def effective_settings(business: Business, phone_number: BusinessPhoneNumber) -> dict:
    """Returns the rule set after business defaults and local exceptions merge."""
    return _deep_merge(
        _deep_merge(DEFAULT_BUSINESS_SETTINGS, business.settings),
        phone_number.settings,
    )


def ensure_legacy_business(db: DBSession) -> Business:
    """Creates the compatibility tenant used while dynamic routing is disabled."""
    existing = db.get(Business, LEGACY_BUSINESS_ID)
    if existing is not None:
        return existing
    business = Business(
        id=LEGACY_BUSINESS_ID,
        name="NTX Automation Co. Demo",
        slug="ntx-demo",
        status="active",
        settings={},
    )
    db.add(business)
    db.commit()
    db.refresh(business)
    return business


def resolve_inbound_business(db: DBSession, twilio_to_number: str) -> TenantContext | None:
    """Looks up the active tenant solely from the receiving Twilio number."""
    normalized = normalize_phone(twilio_to_number)
    if not normalized:
        return None

    row = db.execute(
        select(BusinessPhoneNumber, Business)
        .join(Business, BusinessPhoneNumber.business_id == Business.id)
        .where(
            BusinessPhoneNumber.phone == normalized,
            BusinessPhoneNumber.enabled.is_(True),
            Business.status == "active",
        )
    ).one_or_none()
    if row is None:
        return None

    phone_number, business = row
    return TenantContext(
        business=business,
        phone_number=phone_number,
        settings=effective_settings(business, phone_number),
    )


def build_runtime_tenant(context: TenantContext) -> RuntimeTenant:
    """Validates a stored tenant configuration before customer data is processed."""
    intake = context.settings.get("intake") or {}
    selection_mode = str(intake.get("selection_mode") or "single").strip().lower()
    if selection_mode not in {"single", "menu"}:
        raise TenantConfigError("intake.selection_mode must be 'single' or 'menu'")

    raw_enabled = intake.get("enabled_profiles") or []
    enabled: list[str] = []
    for raw_key in raw_enabled:
        key = resolve_profile_key(str(raw_key))
        if key is None:
            raise TenantConfigError(f"Unknown enabled intake profile: {raw_key}")
        if key not in enabled:
            enabled.append(key)

    raw_default = intake.get("default_profile_key") or context.business.default_profile_key
    default_key = resolve_profile_key(str(raw_default)) if raw_default else None
    if raw_default and default_key is None:
        raise TenantConfigError(f"Unknown default intake profile: {raw_default}")

    if selection_mode == "single":
        if default_key is None:
            if len(enabled) == 1:
                default_key = enabled[0]
            else:
                raise TenantConfigError("Single-profile businesses require a default profile")
        enabled = [default_key]
    elif not enabled:
        raise TenantConfigError("Menu businesses require at least one enabled profile")

    return RuntimeTenant(
        business_id=context.business.id,
        business_name=context.business.name,
        enabled_profile_keys=tuple(key for key in enabled if key in PROFILES),
        default_profile_key=None if selection_mode == "menu" else default_key,
        show_profile_menu=selection_mode == "menu",
        is_demo=bool(intake.get("demo_disclaimer", False)),
        settings=context.settings,
    )


def create_business(
    db: DBSession,
    *,
    name: str,
    slug: str,
    settings: dict | None = None,
    default_profile_key: str | None = None,
) -> Business:
    """Admin-only service function used by the future dashboard route."""
    business = Business(
        id=str(uuid4()),
        name=name.strip(),
        slug=slug.strip().lower(),
        settings=settings or {},
        default_profile_key=default_profile_key,
        status="active",
    )
    db.add(business)
    db.flush()
    return business


def assign_phone_number(
    db: DBSession,
    *,
    business_id: str,
    phone: str,
    label: str | None = None,
    settings: dict | None = None,
) -> BusinessPhoneNumber:
    """Admin-only service function for a business's Twilio number/location."""
    phone_number = BusinessPhoneNumber(
        business_id=business_id,
        phone=normalize_phone(phone),
        label=(label or "").strip() or None,
        settings=settings or {},
        enabled=True,
    )
    db.add(phone_number)
    db.flush()
    return phone_number


def record_audit_event(
    db: DBSession,
    *,
    action: str,
    target_type: str,
    business_id: str | None = None,
    actor_user_id: str | None = None,
    target_id: str | None = None,
    details: dict | None = None,
) -> AuditEvent:
    """Records sensitive actions; it never deletes or mutates prior events."""
    event = AuditEvent(
        business_id=business_id,
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details or {},
    )
    db.add(event)
    db.flush()
    return event
