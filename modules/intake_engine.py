"""
intake_engine.py
Application-controlled field sequencing.

The model may extract structured data, but THIS module — not the LLM —
decides which required field to ask about next, and whether an intake is
complete. This keeps question order deterministic across every profile.
"""

from modules.profiles import Profile, FieldSpec


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
