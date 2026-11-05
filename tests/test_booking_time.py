"""Natural-language time parsing must not guess an unsafe appointment time."""

from datetime import datetime, timezone

from modules.booking_time import parse_requested_time

NOW = datetime(2026, 11, 5, 16, tzinfo=timezone.utc)


def test_relative_weekday_and_exact_time():
    assert parse_requested_time("Yes Friday at 7pm", "America/Chicago", now=NOW) == datetime(2026, 11, 7, 1, tzinfo=timezone.utc)
    assert parse_requested_time("next Tuesday at 4pm", "America/Chicago", now=NOW) == datetime(2026, 11, 10, 22, tzinfo=timezone.utc)
    assert parse_requested_time("tomorrow 4:30 PM", "America/Chicago", now=NOW) == datetime(2026, 11, 6, 22, 30, tzinfo=timezone.utc)


def test_absolute_dates_and_24_hour_clocks():
    expected = datetime(2026, 11, 10, 22, tzinfo=timezone.utc)
    assert parse_requested_time("2026-11-10 16:00", "America/Chicago", now=NOW) == expected
    assert parse_requested_time("Tuesday, Nov 10 at 4 pm", "America/Chicago", now=NOW) == expected
    assert parse_requested_time("11/10/2026 at 4pm", "America/Chicago", now=NOW) == expected


def test_vague_conflicting_and_range_inputs_are_not_guessed():
    for phrase in (
        "Tuesday afternoon", "Friday", "7pm", "Friday at 4",
        "Friday from 4-5pm", "Friday 4pm or 7pm",
        "Friday, Nov 10 at 4pm", "2026-03-08 02:30",
    ):
        assert parse_requested_time(phrase, "America/Chicago", now=NOW) is None
