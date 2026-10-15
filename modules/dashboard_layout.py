"""Tenant-safe, client-configurable dashboard layouts.

Layouts belong to ``Business.settings`` rather than the browser or a global
profile.  That lets everyone at one business share the same Overview while
keeping each tenant fully isolated.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from modules.models import Business


OVERVIEW_WIDGETS = (
    "stats",
    "recent_leads",
    "appointments",
    "recent_conversations",
    "services",
)
MAIN_OVERVIEW_WIDGETS = OVERVIEW_WIDGETS[:-1]
DEFAULT_OVERVIEW_ORDER = list(MAIN_OVERVIEW_WIDGETS)
DEFAULT_SERVICES_POSITION = "right"


def available_overview_widgets(enabled_modules: set[str]) -> set[str]:
    """Return only widgets that the business is entitled to see."""
    available: set[str] = set()
    if enabled_modules & {"leads", "conversations", "appointments", "ai_intake"}:
        available.add("stats")
    if "leads" in enabled_modules:
        available.add("recent_leads")
    if "appointments" in enabled_modules:
        available.add("appointments")
    if "conversations" in enabled_modules:
        available.add("recent_conversations")
    if any(key != "overview" for key in enabled_modules):
        available.add("services")
    return available


def normalize_overview_layout(raw: object, enabled_modules: set[str]) -> dict[str, Any]:
    """Return a complete, safe layout while ignoring unknown client input."""
    source = raw if isinstance(raw, dict) else {}
    raw_order = source.get("order")
    order = [
        key
        for key in raw_order
        if isinstance(key, str) and key in MAIN_OVERVIEW_WIDGETS
    ] if isinstance(raw_order, list) else []
    order.extend(key for key in DEFAULT_OVERVIEW_ORDER if key not in order)

    raw_visible = source.get("visible")
    visibility_source = raw_visible if isinstance(raw_visible, dict) else {}
    visible = {
        key: bool(visibility_source[key]) if isinstance(visibility_source.get(key), bool) else True
        for key in OVERVIEW_WIDGETS
    }
    position = source.get("services_position")
    services_position = position if position in {"left", "right"} else DEFAULT_SERVICES_POSITION

    return {
        "order": order,
        "visible": visible,
        "services_position": services_position,
        "available_widgets": [key for key in OVERVIEW_WIDGETS if key in available_overview_widgets(enabled_modules)],
    }


def for_business(business: Business, enabled_modules: set[str]) -> dict[str, dict[str, Any]]:
    """Build the public layout payload for a business.

    ``available_widgets`` is calculated server-side from entitlements.  The
    browser can never reveal a widget for a module the business does not own.
    """
    settings = business.settings or {}
    raw_layout = settings.get("dashboard_layout")
    source = raw_layout.get("overview") if isinstance(raw_layout, dict) else {}
    return {"overview": normalize_overview_layout(source, enabled_modules)}


def save_for_business(
    business: Business,
    raw_layout: object,
    enabled_modules: set[str],
) -> dict[str, dict[str, Any]]:
    """Normalize and persist the layout without overwriting unrelated settings."""
    source = raw_layout if isinstance(raw_layout, dict) else {}
    overview_source = source.get("overview")
    normalized = normalize_overview_layout(overview_source, enabled_modules)
    persisted_overview = {
        "order": normalized["order"],
        "visible": normalized["visible"],
        "services_position": normalized["services_position"],
    }

    settings = deepcopy(business.settings or {})
    dashboard_layout = settings.get("dashboard_layout")
    dashboard_layout = deepcopy(dashboard_layout) if isinstance(dashboard_layout, dict) else {}
    dashboard_layout["overview"] = persisted_overview
    settings["dashboard_layout"] = dashboard_layout
    business.settings = settings
    return {"overview": normalized}
