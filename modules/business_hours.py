"""
business_hours.py
Detects whether the current time falls within configured business hours
and returns the appropriate SMS greeting.

All settings come from environment variables — nothing is hardcoded.
"""

import os
import logging
import zoneinfo
from datetime import datetime

logger = logging.getLogger(__name__)


def is_business_hours() -> bool:
    """
    Returns True if right now is within business hours.

    Reads from .env:
        BUSINESS_OPEN_HOUR   — int, 24-hour (e.g. 8)
        BUSINESS_CLOSE_HOUR  — int, 24-hour (e.g. 17)
        BUSINESS_WORKDAYS    — comma-separated ints, 0=Mon (e.g. "0,1,2,3,4")
        BUSINESS_TIMEZONE    — IANA tz string (e.g. "America/New_York")

    Fails open (returns True) if any config is missing or invalid,
    so a misconfiguration never silently breaks the greeting.
    """
    try:
        tz_name = os.getenv("BUSINESS_TIMEZONE", "UTC")
        tz = zoneinfo.ZoneInfo(tz_name)
        now = datetime.now(tz)

        open_hour  = int(os.getenv("BUSINESS_OPEN_HOUR",  8))
        close_hour = int(os.getenv("BUSINESS_CLOSE_HOUR", 17))

        raw_workdays = os.getenv("BUSINESS_WORKDAYS", "0,1,2,3,4")
        workdays = [int(d.strip()) for d in raw_workdays.split(",")]

        is_workday  = now.weekday() in workdays
        is_open_now = open_hour <= now.hour < close_hour

        return is_workday and is_open_now

    except Exception as e:
        logger.warning(f"[business_hours] Config error: {e}. Defaulting to open.")
        return True


def get_greeting() -> str:
    """
    Returns the business-hours-aware opening SMS greeting.
    Uses BUSINESS_NAME from env; falls back to "we" language if not set.
    """
    if is_business_hours():
        return (
            "Hey, sorry we missed your call! We can grab a few quick details "
            "so the team can follow up. What can we help you with?"
        )
    else:
        return (
            "Hey, sorry we missed your call! We're currently closed, but go "
            "ahead and share your details and the team will follow up first "
            "thing when we're back."
        )
