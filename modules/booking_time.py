"""Strict timezone-aware parsing for customer-provided appointment preferences.

Only unambiguous date + clock-time combinations are eligible for automatic
booking. Ambiguous phrasing stays pending for clarification, not AI guessing.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

WEEKDAYS = {day.lower(): index for index, day in enumerate(calendar.day_name)}
MONTHS = {month.lower(): index for index, month in enumerate(calendar.month_name) if month}
CLOCK = re.compile(r"(?<![\d:])(?P<hour>1[0-2]|0?[1-9])(?::(?P<minute>[0-5]\d))?\s*(?P<ampm>a\.?m\.?|p\.?m\.?)(?![a-z])", re.I)
CLOCK24 = re.compile(r"(?<!\d)(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)(?!\d)")
DATE_ISO = re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b")
DATE_NUMERIC = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(20\d{2}))?\b")
MONTH_DATE = re.compile(
    r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(20\d{2}))?\b",
    re.I,
)
WEEKDAY = re.compile(r"\b(?:next\s+|this\s+)?(" + "|".join(WEEKDAYS) + r")\b", re.I)


def _localize_strict(day: date, hour: int, minute: int, zone: ZoneInfo) -> datetime | None:
    wall = datetime(day.year, day.month, day.day, hour, minute)
    local = wall.replace(tzinfo=zone)
    # Ambiguous and skipped DST clock hours must be clarified, never guessed.
    if local.utcoffset() != wall.replace(tzinfo=zone, fold=1).utcoffset():
        return None
    if local.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != wall:
        return None
    return local.astimezone(timezone.utc)


def parse_requested_time(value: str, timezone_name: str, *, now: datetime | None = None) -> datetime | None:
    """Return UTC or None. Supports 'Friday at 7pm', 'tomorrow 4:30 PM',
    'Nov 10 at 4pm', '2026-11-10 16:00' and 'next Tuesday 4pm'.

    Never invent AM/PM for bare numbers, nor guess from ranges / multiple times.
    """
    phrase = str(value or "").strip().lower()
    if not phrase or len(phrase) > 160 or re.search(r"\d\s*(?:-|to)\s*\d", phrase):
        return None
    zone = ZoneInfo(timezone_name)
    moment = (now or datetime.now(timezone.utc)).astimezone(zone)
    matched = list(CLOCK.finditer(phrase))
    clocks24 = list(CLOCK24.finditer(phrase))
    # ISO dates contain no HH:MM; match 24h clock only when it is distinct.
    if matched and clocks24:
        clocks24 = [m for m in clocks24 if not any(x.start() <= m.start() < x.end() for x in matched)]
    if len(matched) + len(clocks24) != 1:
        return None
    if matched:
        m = matched[0]
        hour = int(m.group("hour")) % 12 + (12 if m.group("ampm").startswith("p") else 0)
        minute = int(m.group("minute") or 0)
    else:
        m = clocks24[0]
        hour, minute = int(m.group("hour")), int(m.group("minute"))

    target = None
    iso_match = DATE_ISO.search(phrase)
    numeric_match = DATE_NUMERIC.search(phrase)
    month_match = MONTH_DATE.search(phrase)
    try:
        if iso_match:
            target = date(*map(int, iso_match.groups()))
        elif numeric_match:
            month, day, year = numeric_match.groups()
            target = date(int(year or moment.year), int(month), int(day))
            if year is None and target < moment.date() - timedelta(days=1):
                target = target.replace(year=target.year + 1)
        elif month_match:
            month_name, day, year = month_match.groups()
            target = date(int(year or moment.year), MONTHS[month_name], int(day))
            if year is None and target < moment.date() - timedelta(days=1):
                target = target.replace(year=target.year + 1)
        elif "day after tomorrow" in phrase:
            target = moment.date() + timedelta(days=2)
        elif re.search(r"\btomorrow\b", phrase):
            target = moment.date() + timedelta(days=1)
        elif re.search(r"\btoday\b|\btonight\b", phrase):
            target = moment.date()
        else:
            weekday = WEEKDAY.search(phrase)
            if weekday:
                index = WEEKDAYS[weekday.group(1)]
                days = (index - moment.weekday()) % 7
                if days == 0:
                    days = 7 if phrase[weekday.start():weekday.end()].startswith("next") else 0
                target = moment.date() + timedelta(days=days)
    except (ValueError, OverflowError):
        return None
    if target is None:
        return None
    result = _localize_strict(target, hour, minute, zone)
    if result is None:
        return None
    # "Friday at 4pm" on Friday after 4 PM means the next Friday.
    if result <= moment.astimezone(timezone.utc) and not (iso_match or numeric_match or month_match or "tomorrow" in phrase or "today" in phrase or "tonight" in phrase):
        return _localize_strict(target + timedelta(days=7), hour, minute, zone)
    return result
