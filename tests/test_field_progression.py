"""
Required-field progression for every profile, and one-question-at-a-time
behavior: application code (not the model) must pick the next field, in
profile-declared order, and must never ask about a field already filled.
"""

from unittest.mock import patch

import pytest

from tests.conftest import send_sms, fake_ai_result
from modules.profiles import PROFILES
from modules.intake_engine import next_missing_field


PROFILE_MENU_NUMBERS = {"auto_repair": "1", "roofing": "2", "painting": "3", "lawn_care": "4", "catering": "5"}


@pytest.mark.parametrize("profile_key", list(PROFILES.keys()))
def test_next_missing_field_follows_declared_order(profile_key):
    profile = PROFILES[profile_key]
    required_keys = profile.required_field_keys()

    fields: dict = {}
    seen_order = []
    for _ in required_keys:
        field = next_missing_field(profile, fields)
        assert field is not None
        seen_order.append(field.key)
        fields[field.key] = "some answer"

    assert seen_order == required_keys
    assert next_missing_field(profile, fields) is None  # all required fields collected


@pytest.mark.parametrize("profile_key", list(PROFILES.keys()))
def test_app_asks_one_field_at_a_time_via_openai_call(demo_app, profile_key):
    profile = PROFILES[profile_key]
    phone = f"+1555222{profile.menu_number}000"

    send_sms(demo_app, phone, "hi")
    send_sms(demo_app, phone, PROFILE_MENU_NUMBERS[profile_key])

    captured_next_fields = []

    def _capture(history, *, profile, is_demo, is_business_hours, business_name, next_field):
        captured_next_fields.append(next_field.key if next_field else None)
        return fake_ai_result(profile)

    with patch("modules.openai_helper.get_ai_response", side_effect=_capture):
        send_sms(demo_app, phone, "some answer")
        send_sms(demo_app, phone, "another answer")

    # First required field should never be asked about twice in a row when
    # nothing was extracted (each call should target the same still-missing
    # first field, since our fake AI never extracts anything).
    first_required = profile.required_field_keys()[0]
    assert captured_next_fields[0] == first_required
    assert captured_next_fields[1] == first_required
