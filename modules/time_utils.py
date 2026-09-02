"""
time_utils.py
All timestamps are stored in UTC. User- and operator-facing displays are
converted to DEFAULT_TIMEZONE (America/Chicago by default).
"""

import os
import zoneinfo
from datetime import datetime, timezone


def get_display_timezone() -> zoneinfo.ZoneInfo:
    tz_name = os.getenv("DEFAULT_TIMEZONE", "America/Chicago")
    try:
        return zoneinfo.ZoneInfo(tz_name)
    except Exception:
        return zoneinfo.ZoneInfo("America/Chicago")


def to_display_string(dt: datetime) -> str:
    """Formats a UTC-aware datetime for display in DEFAULT_TIMEZONE."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(get_display_timezone())
    return local.strftime("%Y-%m-%d %I:%M %p %Z")
