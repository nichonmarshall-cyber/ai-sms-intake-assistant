from datetime import datetime
from zoneinfo import ZoneInfo

from modules.date_resolution import (
    business_time_context,
    normalize_relative_date_fields,
    resolve_relative_date_phrase,
)


CENTRAL_NOW = datetime(2026, 10, 14, 20, 30, tzinfo=ZoneInfo("America/Chicago"))


def test_tomorrow_resolves_in_the_business_timezone():
    resolved = resolve_relative_date_phrase(
        "tomorrow after 1 PM",
        timezone_name="America/Chicago",
        now=CENTRAL_NOW,
    )

    assert resolved == "Thursday, October 15, 2026 (tomorrow after 1 PM)"


def test_next_weekday_uses_the_following_calendar_week():
    resolved = resolve_relative_date_phrase(
        "next Thursday",
        timezone_name="America/Chicago",
        now=CENTRAL_NOW,
    )

    assert resolved == "Thursday, October 22, 2026 (next Thursday)"


def test_this_weekday_uses_the_upcoming_day_in_the_current_week():
    resolved = resolve_relative_date_phrase(
        "this Thursday morning",
        timezone_name="America/Chicago",
        now=CENTRAL_NOW,
    )

    assert resolved == "Thursday, October 15, 2026 (this Thursday morning)"


def test_only_schedule_fields_are_normalized():
    fields = normalize_relative_date_fields(
        {"preferred_visit_time": "tomorrow", "customer_name": "Tomorrow Jones"},
        date_field_keys={"preferred_visit_time"},
        settings={"calendar": {"timezone": "America/Chicago"}},
        now=CENTRAL_NOW,
    )

    assert fields["preferred_visit_time"] == "Thursday, October 15, 2026 (tomorrow)"
    assert fields["customer_name"] == "Tomorrow Jones"


def test_prompt_context_uses_the_tenant_timezone():
    context = business_time_context(
        {"business_hours": {"timezone": "America/Chicago"}},
        now=CENTRAL_NOW,
    )

    assert "Wednesday, October 14, 2026" in context
    assert "America/Chicago" in context
