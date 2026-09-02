from unittest.mock import patch

import pytest

from modules.conversation_policy import enforce_reply_boundaries
from modules.profiles import PROFILES
from tests.conftest import fake_ai_result, send_sms


@pytest.mark.parametrize("profile", PROFILES.values(), ids=lambda profile: profile.key)
def test_every_profile_has_required_preference_field(profile):
    field = next(f for f in profile.fields if f.key == profile.preference_field_key)
    assert field.required is True
    assert "prefer" in field.question.lower()


@pytest.mark.parametrize("profile_key", list(PROFILES))
def test_pricing_question_is_blocked_across_every_demo_profile(demo_app, profile_key):
    profile = PROFILES[profile_key]
    phone = f"+1555888{profile.menu_number}000"

    send_sms(demo_app, phone, "hello")
    send_sms(demo_app, phone, str(profile.menu_number))

    with patch(
        "modules.openai_helper.get_ai_response",
        return_value=fake_ai_result(
            profile,
            reply="It should cost $500. You're booked for Tuesday.",
            topic_status="off_topic",
        ),
    ):
        _, body = send_sms(demo_app, phone, "How much will this cost?")

    assert "$500" not in body
    assert "Pricing depends on the job" in body
    assert "What&apos;s your name?" in body


def test_unsolicited_model_price_is_replaced():
    reply = enforce_reply_boundaries(
        customer_message="The brakes are squeaking",
        model_reply="That repair is usually 300 dollars.",
        next_field=PROFILES["auto_repair"].fields[0],
    )
    assert "300 dollars" not in reply
    assert "Pricing depends on the job" in reply


def test_model_cannot_confirm_an_appointment():
    reply = enforce_reply_boundaries(
        customer_message="Tuesday works",
        model_reply="You're booked for Tuesday at 2pm.",
        next_field=None,
    )
    assert "You're booked" not in reply
    assert "isn't a confirmed appointment" in reply


@pytest.mark.parametrize("profile_key", list(PROFILES))
def test_every_demo_profile_finishes_with_human_confirmation_boundary(demo_app, profile_key):
    profile = PROFILES[profile_key]
    phone = f"+1555999{profile.menu_number}000"
    complete_fields = {field.key: "details" for field in profile.fields}
    complete_fields["customer_name"] = "Nicholas"
    complete_fields[profile.preference_field_key] = "Tuesday afternoon"

    send_sms(demo_app, phone, "hello")
    send_sms(demo_app, phone, str(profile.menu_number))

    with patch(
        "modules.openai_helper.get_ai_response",
        return_value=fake_ai_result(profile, extracted_fields=complete_fields),
    ):
        _, body = send_sms(demo_app, phone, "Here are all the details")

    assert "Tuesday afternoon" in body
    assert "not a confirmed appointment" in body
    assert "confirm pricing and availability" in body
    assert "Demo only; nothing was booked" in body
