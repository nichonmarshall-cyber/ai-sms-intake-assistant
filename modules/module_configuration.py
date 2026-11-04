"""Validation and persistence for configurable paid business modules."""

from __future__ import annotations

from copy import deepcopy
import re

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from modules.models import BusinessModuleConfiguration
from modules.tenancy import DEFAULT_BUSINESS_SETTINGS


CONFIGURABLE_MODULES = {"ai_memory", "ai_scheduling"}
SCHEMA_VERSION = 1
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
FIELD_TYPES = {
    "text", "long_text", "number", "boolean", "date", "datetime",
    "choice", "phone", "email", "url",
}
AI_VISIBILITY = {"hidden", "read_only", "proposed_update"}
UPDATE_AUTHORITIES = {"employee_only", "ai_proposal", "deterministic_rule"}
SENSITIVITY_LEVELS = {"standard", "sensitive", "restricted"}
BOOKING_MODES = {"approval_required", "automatic"}


class ConfigurationValidationError(ValueError):
    pass


class ConfigurationConflictError(RuntimeError):
    pass


def default_configuration(module_key: str) -> dict:
    if module_key not in CONFIGURABLE_MODULES:
        raise ConfigurationValidationError("This module does not support configuration.")
    return deepcopy(DEFAULT_BUSINESS_SETTINGS[module_key])


def _object(value, label: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigurationValidationError(f"{label} must be an object.")
    return value


def _list(value, label: str, maximum: int) -> list:
    if not isinstance(value, list):
        raise ConfigurationValidationError(f"{label} must be a list.")
    if len(value) > maximum:
        raise ConfigurationValidationError(f"{label} cannot contain more than {maximum} items.")
    return value


def _key(value, label: str) -> str:
    cleaned = str(value or "").strip().lower()
    if not KEY_PATTERN.fullmatch(cleaned):
        raise ConfigurationValidationError(
            f"{label} must start with a letter and use only lowercase letters, numbers, and underscores."
        )
    return cleaned


def _label(value, label: str, maximum: int = 100) -> str:
    cleaned = str(value or "").strip()
    if not cleaned or len(cleaned) > maximum:
        raise ConfigurationValidationError(f"{label} must be between 1 and {maximum} characters.")
    return cleaned


def _integer(value, label: str, minimum: int, maximum: int, *, nullable: bool = False):
    if nullable and value is None:
        return None
    if isinstance(value, bool):
        raise ConfigurationValidationError(f"{label} must be a whole number.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationValidationError(f"{label} must be a whole number.") from exc
    if parsed < minimum or parsed > maximum:
        raise ConfigurationValidationError(f"{label} must be between {minimum} and {maximum}.")
    return parsed


def _validate_memory(configuration: dict) -> dict:
    raw = _object(configuration, "AI Memory configuration")
    allowed = {
        "rolling_summary_enabled", "summary_max_characters", "retention_days",
        "record_types", "status_pipelines",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise ConfigurationValidationError(f"Unknown AI Memory setting: {sorted(unknown)[0]}.")

    record_types = []
    record_keys: set[str] = set()
    for index, record in enumerate(_list(raw.get("record_types", []), "record_types", 25)):
        item = _object(record, f"record_types[{index}]")
        key = _key(item.get("key"), f"record_types[{index}].key")
        if key in record_keys:
            raise ConfigurationValidationError(f"Duplicate record type key: {key}.")
        record_keys.add(key)
        fields = []
        field_keys: set[str] = set()
        for field_index, field in enumerate(_list(item.get("fields", []), f"{key}.fields", 50)):
            field = _object(field, f"{key}.fields[{field_index}]")
            field_key = _key(field.get("key"), f"{key}.fields[{field_index}].key")
            if field_key in field_keys:
                raise ConfigurationValidationError(f"Duplicate field key on {key}: {field_key}.")
            field_keys.add(field_key)
            field_type = str(field.get("type") or "text")
            visibility = str(field.get("ai_visibility") or "read_only")
            authority = str(field.get("update_authority") or "employee_only")
            sensitivity = str(field.get("sensitivity") or "standard")
            if field_type not in FIELD_TYPES:
                raise ConfigurationValidationError(f"Unsupported field type: {field_type}.")
            if visibility not in AI_VISIBILITY:
                raise ConfigurationValidationError(f"Unsupported AI visibility: {visibility}.")
            if authority not in UPDATE_AUTHORITIES:
                raise ConfigurationValidationError(f"Unsupported update authority: {authority}.")
            if sensitivity not in SENSITIVITY_LEVELS:
                raise ConfigurationValidationError(f"Unsupported sensitivity: {sensitivity}.")
            if sensitivity == "restricted" and visibility != "hidden":
                raise ConfigurationValidationError("Restricted fields must be hidden from AI context.")
            fields.append({
                "key": field_key,
                "label": _label(field.get("label"), f"{key}.{field_key}.label"),
                "type": field_type,
                "ai_visibility": visibility,
                "update_authority": authority,
                "sensitivity": sensitivity,
                "required": bool(field.get("required", False)),
                "choices": [
                    _label(choice, f"{key}.{field_key}.choices", 80)
                    for choice in _list(field.get("choices", []), f"{key}.{field_key}.choices", 50)
                ] if field_type == "choice" else [],
            })
        record_types.append({"key": key, "label": _label(item.get("label"), f"{key}.label"), "fields": fields})

    pipelines = []
    pipeline_keys: set[str] = set()
    for index, pipeline in enumerate(_list(raw.get("status_pipelines", []), "status_pipelines", 25)):
        item = _object(pipeline, f"status_pipelines[{index}]")
        key = _key(item.get("key"), f"status_pipelines[{index}].key")
        if key in pipeline_keys:
            raise ConfigurationValidationError(f"Duplicate status pipeline key: {key}.")
        pipeline_keys.add(key)
        statuses = []
        status_keys: set[str] = set()
        for status_index, status in enumerate(_list(item.get("statuses", []), f"{key}.statuses", 30)):
            status = _object(status, f"{key}.statuses[{status_index}]")
            status_key = _key(status.get("key"), f"{key}.statuses[{status_index}].key")
            if status_key in status_keys:
                raise ConfigurationValidationError(f"Duplicate status key on {key}: {status_key}.")
            status_keys.add(status_key)
            message = str(status.get("customer_message") or "").strip()
            if len(message) > 500:
                raise ConfigurationValidationError("Customer status messages cannot exceed 500 characters.")
            statuses.append({
                "key": status_key,
                "label": _label(status.get("label"), f"{key}.{status_key}.label"),
                "customer_message": message,
            })
        pipelines.append({"key": key, "label": _label(item.get("label"), f"{key}.label"), "statuses": statuses})

    return {
        "rolling_summary_enabled": bool(raw.get("rolling_summary_enabled", True)),
        "summary_max_characters": _integer(raw.get("summary_max_characters", 1200), "summary_max_characters", 200, 4000),
        "retention_days": _integer(raw.get("retention_days", 365), "retention_days", 30, 3650),
        "record_types": record_types,
        "status_pipelines": pipelines,
    }


def _validate_scheduling(configuration: dict) -> dict:
    raw = _object(configuration, "AI Scheduling configuration")
    allowed = {
        "booking_mode", "buffer_before_minutes", "buffer_after_minutes",
        "minimum_notice_minutes", "maximum_advance_days", "slot_interval_minutes",
        "max_bookings_per_day", "services", "approval_notification_enabled",
        "approval_message_template", "working_hours",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise ConfigurationValidationError(f"Unknown AI Scheduling setting: {sorted(unknown)[0]}.")
    booking_mode = str(raw.get("booking_mode") or "approval_required")
    if booking_mode not in BOOKING_MODES:
        raise ConfigurationValidationError("booking_mode must be approval_required or automatic.")
    message_template = str(raw.get("approval_message_template") or "").strip()
    if not message_template or len(message_template) > 500:
        raise ConfigurationValidationError(
            "approval_message_template must be between 1 and 500 characters."
        )
    allowed_placeholders = {"business_name", "customer_name", "date", "time"}
    placeholders = set(re.findall(r"\{([a-z_]+)\}", message_template))
    unsupported = placeholders - allowed_placeholders
    if unsupported:
        raise ConfigurationValidationError(
            f"Unsupported approval message placeholder: {sorted(unsupported)[0]}."
        )

    raw_hours = _object(raw.get("working_hours", {}), "working_hours")
    working_hours = {}
    for day in range(7):
        item = _object(raw_hours.get(str(day), {}), f"working_hours.{day}")
        start = str(item.get("start") or "08:00")
        end = str(item.get("end") or "17:00")
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", start) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", end):
            raise ConfigurationValidationError("Working hours must use 24-hour HH:MM values.")
        if start >= end:
            raise ConfigurationValidationError("Each enabled day must end after it starts.")
        working_hours[str(day)] = {"enabled": bool(item.get("enabled", False)), "start": start, "end": end}

    services = []
    service_keys: set[str] = set()
    for index, service in enumerate(_list(raw.get("services", []), "services", 50)):
        item = _object(service, f"services[{index}]")
        key = _key(item.get("key"), f"services[{index}].key")
        if key in service_keys:
            raise ConfigurationValidationError(f"Duplicate service key: {key}.")
        service_keys.add(key)
        service_mode = str(item.get("booking_mode") or booking_mode)
        if service_mode not in BOOKING_MODES:
            raise ConfigurationValidationError(f"Invalid booking mode for service {key}.")
        services.append({
            "key": key,
            "label": _label(item.get("label"), f"{key}.label"),
            "duration_minutes": _integer(item.get("duration_minutes", 60), f"{key}.duration_minutes", 15, 480),
            "buffer_before_minutes": _integer(item.get("buffer_before_minutes", raw.get("buffer_before_minutes", 0)), f"{key}.buffer_before_minutes", 0, 240),
            "buffer_after_minutes": _integer(item.get("buffer_after_minutes", raw.get("buffer_after_minutes", 15)), f"{key}.buffer_after_minutes", 0, 240),
            "booking_mode": service_mode,
            "enabled": bool(item.get("enabled", True)),
        })

    return {
        "booking_mode": booking_mode,
        "approval_notification_enabled": bool(raw.get("approval_notification_enabled", True)),
        "approval_message_template": message_template,
        "buffer_before_minutes": _integer(raw.get("buffer_before_minutes", 0), "buffer_before_minutes", 0, 240),
        "buffer_after_minutes": _integer(raw.get("buffer_after_minutes", 15), "buffer_after_minutes", 0, 240),
        "minimum_notice_minutes": _integer(raw.get("minimum_notice_minutes", 120), "minimum_notice_minutes", 0, 43200),
        "maximum_advance_days": _integer(raw.get("maximum_advance_days", 60), "maximum_advance_days", 1, 365),
        "slot_interval_minutes": _integer(raw.get("slot_interval_minutes", 15), "slot_interval_minutes", 5, 120),
        "max_bookings_per_day": _integer(raw.get("max_bookings_per_day"), "max_bookings_per_day", 1, 500, nullable=True),
        "working_hours": working_hours,
        "services": services,
    }


def validate_configuration(module_key: str, configuration: dict) -> dict:
    if module_key == "ai_memory":
        return _validate_memory(configuration)
    if module_key == "ai_scheduling":
        return _validate_scheduling(configuration)
    raise ConfigurationValidationError("This module does not support configuration.")


def get_configuration(db: DBSession, business_id: str, module_key: str) -> tuple[dict, int]:
    default = default_configuration(module_key)
    row = db.execute(
        select(BusinessModuleConfiguration).where(
            BusinessModuleConfiguration.business_id == business_id,
            BusinessModuleConfiguration.module_key == module_key,
        )
    ).scalar_one_or_none()
    if row is None:
        return validate_configuration(module_key, default), 0
    # Read-time validation also supplies defaults introduced by later schema
    # revisions, so pre-existing tenant settings remain safe and usable.
    return validate_configuration(module_key, deepcopy(row.configuration)), row.version


def save_configuration(
    db: DBSession,
    business_id: str,
    module_key: str,
    configuration: dict,
    *,
    expected_version: int | None,
) -> BusinessModuleConfiguration:
    validated = validate_configuration(module_key, configuration)
    row = db.execute(
        select(BusinessModuleConfiguration).where(
            BusinessModuleConfiguration.business_id == business_id,
            BusinessModuleConfiguration.module_key == module_key,
        )
    ).scalar_one_or_none()
    current_version = row.version if row is not None else 0
    if expected_version is not None and expected_version != current_version:
        raise ConfigurationConflictError(
            "This configuration changed after you opened it. Refresh and try again."
        )
    if row is None:
        row = BusinessModuleConfiguration(
            business_id=business_id,
            module_key=module_key,
            configuration=validated,
            schema_version=SCHEMA_VERSION,
            version=1,
        )
        db.add(row)
    else:
        row.configuration = validated
        row.schema_version = SCHEMA_VERSION
        row.version += 1
    db.flush()
    return row
