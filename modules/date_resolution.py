"""Business-local interpretation of relative appointment language.

The intake assistant stores a customer's original preference, but adds the
unambiguous calendar date whenever they use a phrase such as ``tomorrow`` or
``next Thursday``.  This keeps the conversation, lead record, and dashboard
in the business's timezone instead of depending on the server clock.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_WEEKDAY_PATTERN = re.compile(
    r"\b(?:(?P<modifier>this|next)\s+)?"
    r"(?P<weekday>monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)


def business_timezone(settings: dict | None = None) -> str:
    """Return a valid tenant timezone, with Central time as the safe default."""
    settings = settings or {}
    candidates = (
        (settings.get("calendar") or {}).get("timezone"),
        (settings.get("business_hours") or {}).get("timezone"),
        settings.get("timezone"),
        os.getenv("DEFAULT_TIMEZONE"),
        os.getenv("BUSINESS_TIMEZONE"),
        "America/Chicago",
    )
    for candidate in candidates:
        name = str(candidate or "").strip()
        if not name:
            continue
        try:
            ZoneInfo(name)
            return name
        except ZoneInfoNotFoundError:
            continue
    return "America/Chicago"


def _local_now(timezone_name: str, now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(ZoneInfo(timezone_name))


def _format_date(value) -> str:
    return f"{value.strftime('%A, %B')} {value.day}, {value.year}"


def resolve_relative_date_phrase(
    value: str,
    *,
    timezone_name: str,
    now: datetime | None = None,
) -> str:
    """Add an exact local date to a relative date phrase when one is present.

    ``next Thursday`` means the Thursday in the following calendar week;
    ``this Thursday`` and bare ``Thursday`` mean the upcoming occurrence in
    the current week. The original customer wording stays in parentheses so
    timing details such as "after 1 PM" are never thrown away.
    """
    original = str(value or "").strip()
    if not original:
        return original

    local_now = _local_now(timezone_name, now)
    lower = original.lower()
    target_date = None

    if re.search(r"\bday after tomorrow\b", lower):
        target_date = local_now.date() + timedelta(days=2)
    elif re.search(r"\btomorrow\b", lower):
        target_date = local_now.date() + timedelta(days=1)
    elif re.search(r"\btoday\b", lower):
        target_date = local_now.date()
    else:
        match = _WEEKDAY_PATTERN.search(lower)
        if match:
            target_weekday = _WEEKDAYS[match.group("weekday").lower()]
            days_until = (target_weekday - local_now.weekday()) % 7
            modifier = match.group("modifier")
            if modifier == "next":
                days_until += 7
            target_date = local_now.date() + timedelta(days=days_until)

    if target_date is None:
        return original
    return f"{_format_date(target_date)} ({original})"


def normalize_relative_date_fields(
    fields: dict | None,
    *,
    date_field_keys: set[str],
    settings: dict | None = None,
    now: datetime | None = None,
) -> dict:
    """Return extracted intake fields with relative schedule dates clarified."""
    normalized = dict(fields or {})
    timezone_name = business_timezone(settings)
    for key in date_field_keys:
        value = normalized.get(key)
        if isinstance(value, str):
            normalized[key] = resolve_relative_date_phrase(
                value,
                timezone_name=timezone_name,
                now=now,
            )
    return normalized


def business_time_context(settings: dict | None = None, *, now: datetime | None = None) -> str:
    """Give the model the same exact temporal reference used by normalization."""
    timezone_name = business_timezone(settings)
    local_now = _local_now(timezone_name, now)
    return (
        f"The business's local date and time is {local_now.strftime('%A, %B')} "
        f"{local_now.day}, {local_now.year} at {local_now.strftime('%-I:%M %p')} "
        f"({timezone_name})."
    )
