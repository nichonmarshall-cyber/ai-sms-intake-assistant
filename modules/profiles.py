"""
profiles.py
Structured, declarative configuration for every supported industry profile.

Each profile defines:
  - key                : stable machine identifier (used in DB, env vars, code)
  - display_name        : human-readable name shown in the demo menu
  - menu_number         : the digit customers can reply with (1-5)
  - aliases             : lowercase strings that should also match this profile
                           when a customer types a name instead of a number
  - business_type_label  : short phrase used inside the system prompt
                           ("auto repair shop", "roofing company", ...)
  - industry_instructions: profile-specific guidance appended to the shared
                           system prompt (what to ask about, category list)
  - categories           : valid classification categories for this profile
  - fields                : ordered list of FieldSpec — application code (not
                           the model) decides which of these to ask for next

No `if business_type == "..."` branching exists elsewhere in the app —
every place that needs industry-specific behavior reads from PROFILES.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass(frozen=True)
class FieldSpec:
    key: str                       # storage key, also the JSON key the AI returns
    label: str                     # human-readable label (used in summaries/sheets)
    question: str                  # deterministic fallback question for this field
    required: bool = True
    # Optional validator: (raw_value) -> (is_valid, cleaned_value_or_error_reason)
    validate: Optional[Callable[[str], tuple[bool, str]]] = None


@dataclass(frozen=True)
class Profile:
    key: str
    display_name: str
    menu_number: int
    aliases: tuple[str, ...]
    business_type_label: str
    industry_instructions: str
    categories: tuple[str, ...]
    fields: tuple[FieldSpec, ...]

    def field_keys(self) -> list[str]:
        return [f.key for f in self.fields]

    def required_field_keys(self) -> list[str]:
        return [f.key for f in self.fields if f.required]


# ─── Shared validators ────────────────────────────────────────────────────────

def _non_empty(value: str) -> tuple[bool, str]:
    cleaned = (value or "").strip()
    if not cleaned:
        return False, ""
    return True, cleaned


# ─── Profile definitions ──────────────────────────────────────────────────────

AUTO_REPAIR = Profile(
    key="auto_repair",
    display_name="Auto Repair",
    menu_number=1,
    aliases=("auto repair", "auto", "mechanic", "car repair", "vehicle repair", "car"),
    business_type_label="auto repair shop",
    industry_instructions=(
        "You help customers describe a vehicle problem so a mechanic can follow up.\n"
        "Ask about the vehicle year/make/model, the main problem or symptoms, when it "
        "started, and whether the vehicle is currently drivable."
    ),
    categories=(
        "diagnostic", "tire_service", "oil_change", "detailing",
        "quote_request", "general_service", "unknown",
    ),
    fields=(
        FieldSpec("customer_name", "Customer Name", "What's your name?"),
        FieldSpec("vehicle_year", "Vehicle Year", "What year is the vehicle?"),
        FieldSpec("vehicle_make", "Vehicle Make", "What's the make (e.g. Toyota)?"),
        FieldSpec("vehicle_model", "Vehicle Model", "What's the model (e.g. Camry)?"),
        FieldSpec("problem_description", "Problem / Symptoms", "What's going on with the vehicle?"),
        FieldSpec("problem_started", "When It Started", "When did this problem start?"),
        FieldSpec("is_drivable", "Drivable?", "Is the vehicle currently drivable?"),
        FieldSpec("customer_location", "Location", "What's your location or nearest cross streets?"),
        FieldSpec("preferred_callback_time", "Preferred Callback Time", "What's the best time to call you back?"),
    ),
)

ROOFING = Profile(
    key="roofing",
    display_name="Roofing",
    menu_number=2,
    aliases=("roofing", "roof", "roofer"),
    business_type_label="roofing company",
    industry_instructions=(
        "You help customers describe a roofing need so a roofer can follow up.\n"
        "Ask about the property location, the type of service needed (leak, damage, "
        "inspection, replacement, other), when the issue began, and whether water is "
        "actively leaking right now. Treat 'inspect' or 'inspection' as a complete "
        "answer for service type even when the customer also mentions a possible leak."
    ),
    categories=(
        "leak_repair", "storm_damage", "inspection", "replacement",
        "quote_request", "general_service", "unknown",
    ),
    fields=(
        FieldSpec("customer_name", "Customer Name", "What's your name?"),
        FieldSpec("property_location", "Property Location", "What's the property address or location?"),
        FieldSpec("service_type", "Service Type", "What would you like the roofer to check or help with?"),
        FieldSpec("issue_started", "When It Began", "When did this issue start?"),
        FieldSpec("is_active_leak", "Active Leak?", "Is water actively leaking right now?"),
        FieldSpec("roof_type", "Roof Type", "Do you know the roof type (shingle, metal, tile, flat, etc.)?", required=False),
        FieldSpec("preferred_callback_time", "Preferred Callback Time", "What's the best time to call you back?"),
    ),
)

PAINTING = Profile(
    key="painting",
    display_name="Painting",
    menu_number=3,
    aliases=("painting", "paint", "painter"),
    business_type_label="painting company",
    industry_instructions=(
        "You help customers describe a painting job so a painter can follow up.\n"
        "Ask about the property location, whether it's interior or exterior, which "
        "rooms or areas are involved, the current surface condition, desired colors "
        "(if known), and the desired timeline."
    ),
    categories=(
        "interior_painting", "exterior_painting", "touch_up",
        "quote_request", "general_service", "unknown",
    ),
    fields=(
        FieldSpec("customer_name", "Customer Name", "What's your name?"),
        FieldSpec("property_location", "Property Location", "What's the property address or location?"),
        FieldSpec("interior_or_exterior", "Interior / Exterior", "Is this interior or exterior painting?"),
        FieldSpec("areas_involved", "Rooms / Areas", "Which rooms or areas are involved?"),
        FieldSpec("surface_condition", "Surface Condition", "What's the current condition of the surface (peeling, cracked, fresh drywall, etc.)?"),
        FieldSpec("desired_colors", "Desired Colors", "Do you have colors in mind?", required=False),
        FieldSpec("desired_timeline", "Timeline", "What's your desired timeline?"),
        FieldSpec("preferred_callback_time", "Preferred Callback Time", "What's the best time to call you back?"),
    ),
)

LAWN_CARE = Profile(
    key="lawn_care",
    display_name="Lawn Care",
    menu_number=4,
    aliases=("lawn care", "lawn", "landscaping", "yard", "mowing"),
    business_type_label="lawn care company",
    industry_instructions=(
        "You help customers describe a lawn care need so the crew can follow up.\n"
        "Ask about the service address, the requested service, approximate yard/lot "
        "size, whether this is one-time or recurring, and any gate/pet/access info."
    ),
    categories=(
        "mowing", "landscaping", "cleanup", "recurring_service",
        "quote_request", "general_service", "unknown",
    ),
    fields=(
        FieldSpec("customer_name", "Customer Name", "What's your name?"),
        FieldSpec("service_address", "Service Address", "What's the service address?"),
        FieldSpec("requested_service", "Requested Service", "What service are you looking for?"),
        FieldSpec("yard_size", "Yard / Lot Size", "About how big is the yard or lot?", required=False),
        FieldSpec("recurrence", "One-time / Recurring", "Would this be a one-time service or recurring?"),
        FieldSpec("access_info", "Gate / Pet / Access Info", "Anything we should know about gates, pets, or access?", required=False),
        FieldSpec("preferred_callback_time", "Preferred Day / Callback Time", "What day or time works best for you?"),
    ),
)

CATERING = Profile(
    key="catering",
    display_name="Catering",
    menu_number=5,
    aliases=("catering", "cater", "caterer", "food", "event catering"),
    business_type_label="catering company",
    industry_instructions=(
        "You help customers describe a catering need so the events team can follow up.\n"
        "Ask about the event type, event date, guest count, event location, requested "
        "food or cuisine, and any dietary restrictions."
    ),
    categories=(
        "event_catering", "corporate_catering", "private_party",
        "quote_request", "general_service", "unknown",
    ),
    fields=(
        FieldSpec("customer_name", "Customer Name", "What's your name?"),
        FieldSpec("event_type", "Event Type", "What type of event is this?"),
        FieldSpec("event_date", "Event Date", "What's the event date?"),
        FieldSpec("guest_count", "Guest Count", "About how many guests?"),
        FieldSpec("event_location", "Event Location", "Where is the event?"),
        FieldSpec("food_requested", "Requested Food / Cuisine", "What kind of food or cuisine are you looking for?"),
        FieldSpec("dietary_restrictions", "Dietary Restrictions", "Any dietary restrictions we should know about?", required=False),
        FieldSpec("preferred_callback_time", "Preferred Callback Time", "What's the best time to call you back?"),
    ),
)

PROFILES: dict[str, Profile] = {
    p.key: p for p in (AUTO_REPAIR, ROOFING, PAINTING, LAWN_CARE, CATERING)
}

# Legacy alias: mechanic-only production deployments may set
# DEFAULT_PROFILE=mechanic; treat it as auto_repair.
PROFILE_ALIASES = {"mechanic": "auto_repair"}


def resolve_profile_key(raw: str) -> Optional[str]:
    """
    Resolves a raw string (env var value, or already-known key) to a
    canonical profile key, or None if it doesn't match anything.
    """
    if not raw:
        return None
    cleaned = raw.strip().lower()
    cleaned = PROFILE_ALIASES.get(cleaned, cleaned)
    if cleaned in PROFILES:
        return cleaned
    return None


def match_menu_selection(raw_text: str) -> Optional[str]:
    """
    Deterministically matches a customer's raw SMS text against a profile.
    Accepts: menu number ("2"), exact key, display name, or a known alias
    (case-insensitive, punctuation-insensitive substring match).

    Returns the profile key, or None if nothing matched.
    """
    if not raw_text:
        return None

    text = raw_text.strip().lower()
    text = "".join(ch for ch in text if ch.isalnum() or ch.isspace())
    text = text.strip()
    if not text:
        return None

    # Numeric menu selection
    if text.isdigit():
        num = int(text)
        for profile in PROFILES.values():
            if profile.menu_number == num:
                return profile.key
        return None

    # Exact key or display-name match
    for profile in PROFILES.values():
        if text == profile.key.replace("_", " ") or text == profile.key:
            return profile.key
        if text == profile.display_name.lower():
            return profile.key

    # Alias match (exact, then substring in either direction for short input)
    for profile in PROFILES.values():
        if text in profile.aliases:
            return profile.key

    for profile in PROFILES.values():
        for alias in profile.aliases:
            if alias in text or text in alias:
                return profile.key

    return None


def get_enabled_profiles(enabled_keys: Optional[list[str]] = None) -> list[Profile]:
    """
    Returns the list of Profile objects to expose, in menu order.
    If enabled_keys is given (from ENABLED_PROFILES env var), only those
    profiles are returned; unknown keys are ignored.
    """
    if not enabled_keys:
        return sorted(PROFILES.values(), key=lambda p: p.menu_number)

    resolved = []
    for raw in enabled_keys:
        key = resolve_profile_key(raw)
        if key and PROFILES[key] not in resolved:
            resolved.append(PROFILES[key])
    return sorted(resolved, key=lambda p: p.menu_number) or sorted(
        PROFILES.values(), key=lambda p: p.menu_number
    )
