"""
intake_engine.py
Application-controlled field sequencing.

The model may extract structured data, but THIS module — not the LLM —
decides which required field to ask about next, and whether an intake is
complete. This keeps question order deterministic across every profile.
"""

import re

from modules.profiles import Profile, FieldSpec


_COMBINED_VEHICLE_DETAILS = re.compile(
    r"^\s*(?P<year>(?:19|20)\d{2})\s+"
    r"(?P<make>[A-Za-z][A-Za-z0-9-]*)\s+"
    r"(?P<model>[A-Za-z0-9][A-Za-z0-9 ./'-]*?)\s*$"
)


def next_missing_field(profile: Profile, fields: dict) -> FieldSpec | None:
    """Returns the first required field not yet collected, in profile order."""
    for field_spec in profile.fields:
        if not field_spec.required:
            continue
        value = (fields or {}).get(field_spec.key)
        if value is None or (isinstance(value, str) and not value.strip()):
            return field_spec
    return None


def is_intake_complete(profile: Profile, fields: dict) -> bool:
    return next_missing_field(profile, fields) is None


def extract_combined_vehicle_details(
    profile: Profile, text: str, *, expected_field_key: str | None
) -> dict[str, str]:
    """Deterministically split a complete vehicle answer into intake fields.

    The auto-repair flow asks for year, make, and model in sequence, but a
    normal person often gives all three at once.  When the current question is
    the year and the reply is a direct ``YEAR MAKE MODEL`` answer, save every
    provided detail now instead of depending on a model extraction call to
    split it correctly.
    """
    if profile.key != "auto_repair" or expected_field_key != "vehicle_year":
        return {}

    match = _COMBINED_VEHICLE_DETAILS.fullmatch((text or "").strip())
    if match is None:
        return {}

    return {
        "vehicle_year": match.group("year"),
        "vehicle_make": match.group("make"),
        "vehicle_model": match.group("model").strip(),
    }


def validate_extracted_fields(profile: Profile, extracted: dict) -> dict:
    """
    Validates the model's extracted_fields against each field's optional
    validator before they are allowed to update session state. Fields that
    fail validation are dropped (treated as not yet provided) rather than
    trusted blindly.
    """
    allowed_keys = set(profile.field_keys())
    field_by_key = {f.key: f for f in profile.fields}
    cleaned: dict = {}

    for key, value in (extracted or {}).items():
        if key not in allowed_keys:
            continue
        if value is None:
            cleaned[key] = None
            continue

        field_spec = field_by_key[key]
        if field_spec.validate is not None:
            ok, result = field_spec.validate(str(value))
            cleaned[key] = result if ok else None
        else:
            cleaned[key] = value

    return cleaned
