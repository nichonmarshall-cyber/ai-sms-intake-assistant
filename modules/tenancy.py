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


DEFAULT_BUSINESS_SETTINGS = {
    "intake": {
        "enabled_profiles": [],
        "default_profile_key": None,
        "demo_mode": False,
    },
    "missed_calls": {
        "enabled": False,
        "cooldown_minutes": 1440,
    },
}


@dataclass(frozen=True)
class TenantContext:
    business: Business
    phone_number: BusinessPhoneNumber
    settings: dict


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
