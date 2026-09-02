"""
intake_engine.py
Application-controlled field sequencing.

The model may extract structured data, but THIS module — not the LLM —
decides which required field to ask about next, and whether an intake is
complete. This keeps question order deterministic across every profile.
"""

import re
from difflib import get_close_matches

from modules.profiles import Profile, FieldSpec


_COMBINED_VEHICLE_DETAILS = re.compile(
    r"^\s*(?P<year>(?:19|20)\d{2})\s+"
    r"(?P<make>[A-Za-z][A-Za-z0-9-]*)\s+"
    r"(?P<model>[A-Za-z0-9][A-Za-z0-9 ./'-]*?)\s*$"
)
_NATURAL_VEHICLE_DETAILS = re.compile(
    r"^\s*(?:(?:i\s+(?:have|drive|own)|it(?:'s| is))\s+(?:an?\s+)?)?"
    r"(?P<year>\d{2}|(?:19|20)\d{2})\s+"
    r"(?P<make>[A-Za-z][A-Za-z0-9-]*)\s+"
    r"(?P<model>[A-Za-z0-9][A-Za-z0-9 ./'-]*?)\s*$",
    re.IGNORECASE,
)
_VEHICLE_MAKES = (
    "Acura", "Alfa Romeo", "Audi", "BMW", "Buick", "Cadillac", "Chevy",
    "Chrysler", "Dodge", "Fiat", "Ford", "Genesis", "GMC", "Honda",
    "Hyundai", "Infiniti", "Jaguar", "Jeep", "Kia", "Land Rover", "Lexus",
    "Lincoln", "Mazda", "Mercedes", "Mini", "Mitsubishi", "Nissan", "Porsche",
    "Ram", "Subaru", "Tesla", "Toyota", "Volkswagen", "Volvo",
)
_MAKE_ALIASES = {"chevrolet": "Chevy", "mercedes-benz": "Mercedes", "vw": "Volkswagen"}


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

    raw_make = match.group("make").lower()
    canonical_make = _MAKE_ALIASES.get(raw_make) or next(
        (make for make in _VEHICLE_MAKES if make.lower() == raw_make),
        None,
    )
    if canonical_make is None:
        return {}

    return {
        "vehicle_year": match.group("year"),
        "vehicle_make": canonical_make,
        "vehicle_model": match.group("model").strip(),
    }


def infer_uncertain_vehicle_details(
    profile: Profile, text: str, *, expected_field_key: str | None
) -> dict[str, str] | None:
    """Returns a *proposed* vehicle only when it needs customer confirmation."""
    if profile.key != "auto_repair" or expected_field_key != "vehicle_year":
        return None
    match = _NATURAL_VEHICLE_DETAILS.fullmatch((text or "").strip())
    if match is None:
        return None

    raw_year = match.group("year")
    if len(raw_year) == 2:
        # Modern two-digit years are common in text messages. They are never
        # saved without confirmation, even though 23 strongly suggests 2023.
        if int(raw_year) > 30:
            return None
        year = f"20{raw_year}"
        uncertain = True
    else:
        year = raw_year
        uncertain = False

    raw_make = match.group("make").lower()
    canonical_make = _MAKE_ALIASES.get(raw_make)
    if canonical_make is None:
        exact = next((make for make in _VEHICLE_MAKES if make.lower() == raw_make), None)
        if exact is not None:
            canonical_make = exact
        else:
            close = get_close_matches(raw_make, [make.lower() for make in _VEHICLE_MAKES], n=1, cutoff=0.75)
            if not close:
                return None
            canonical_make = next(make for make in _VEHICLE_MAKES if make.lower() == close[0])
            uncertain = True

    if not uncertain:
        return None
    return {
        "vehicle_year": year,
        "vehicle_make": canonical_make,
        "vehicle_model": match.group("model").strip().title(),
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
