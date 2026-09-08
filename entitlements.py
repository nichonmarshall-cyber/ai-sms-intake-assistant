"""Per-business module entitlements.

The registry below is the single source of truth for what a module *is*.
Whether a given business may use one is a database question -- a row in
``business_modules`` with ``enabled = true``.

``implemented`` marks what actually exists today. Phase 1a deliberately ships
locked/coming-later states for the rest rather than mock data, so a client is
never shown a fabricated metric.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from modules.models import BusinessModule


@dataclass(frozen=True)
class ModuleSpec:
    key: str
    label: str
    icon: str
    implemented: bool
    description: str


MODULE_REGISTRY: tuple[ModuleSpec, ...] = (
    ModuleSpec("overview", "Overview", "home", True, "Business performance at a glance."),
    ModuleSpec("leads", "Leads", "users", False, "Lead management arrives in Phase 2."),
    ModuleSpec("conversations", "Conversations", "message-square", False, "SMS timelines arrive in Phase 2."),
    ModuleSpec("ai_intake", "AI Intake", "cpu", False, "Intake monitoring arrives in Phase 2."),
    ModuleSpec("website", "Website", "globe", False, "Requires a monitoring provider."),
    ModuleSpec("local_seo", "Local SEO", "search", False, "Requires Google Search Console."),
    ModuleSpec("reviews", "Reviews", "star", False, "Requires Google Business Profile."),
    ModuleSpec("analytics", "Analytics", "bar-chart", False, "Requires Google Analytics."),
    ModuleSpec("campaigns", "Campaigns", "send", False, "Arrives with the campaign queue in Phase 4."),
    ModuleSpec("contacts", "Contacts", "book", False, "Arrives with the restaurant CRM in Phase 4."),
    ModuleSpec("qr_sources", "QR Sources", "grid", False, "Arrives with the restaurant CRM in Phase 4."),
    ModuleSpec("coupons", "Coupons", "tag", False, "Arrives with the restaurant CRM in Phase 4."),
    ModuleSpec("settings", "Settings", "settings", True, "Business profile and preferences."),
)

MODULE_KEYS = tuple(spec.key for spec in MODULE_REGISTRY)
MODULES_BY_KEY = {spec.key: spec for spec in MODULE_REGISTRY}

# Every business starts with the modules Phase 1a and Phase 2 actually cover.
DEFAULT_ENABLED_MODULES = ("overview", "leads", "conversations", "ai_intake", "settings")


def is_valid_module(module_key: str) -> bool:
    return module_key in MODULES_BY_KEY


def enabled_module_keys(db: DBSession, business_id: str) -> set[str]:
    rows = db.execute(
        select(BusinessModule.module_key).where(
            BusinessModule.business_id == business_id,
            BusinessModule.enabled.is_(True),
        )
    ).scalars()
    return {key for key in rows if key in MODULES_BY_KEY}


def is_module_enabled(db: DBSession, business_id: str, module_key: str) -> bool:
    if not is_valid_module(module_key):
        return False
    return module_key in enabled_module_keys(db, business_id)


def set_module(db: DBSession, business_id: str, module_key: str, enabled: bool) -> BusinessModule:
    if not is_valid_module(module_key):
        raise ValueError(f"Unknown module key: {module_key}")
    row = db.execute(
        select(BusinessModule).where(
            BusinessModule.business_id == business_id,
            BusinessModule.module_key == module_key,
        )
    ).scalar_one_or_none()
    if row is None:
        row = BusinessModule(business_id=business_id, module_key=module_key, enabled=enabled)
        db.add(row)
    else:
        row.enabled = enabled
    db.flush()
    return row


def apply_defaults(db: DBSession, business_id: str) -> None:
    for key in DEFAULT_ENABLED_MODULES:
        set_module(db, business_id, key, True)


def navigation_for(db: DBSession, business_id: str) -> list[dict]:
    """Nav payload for the client dashboard. Disabled modules are omitted."""
    enabled = enabled_module_keys(db, business_id)
    return [
        {
            "key": spec.key,
            "label": spec.label,
            "icon": spec.icon,
            "implemented": spec.implemented,
            "description": spec.description,
        }
        for spec in MODULE_REGISTRY
        if spec.key in enabled
    ]
