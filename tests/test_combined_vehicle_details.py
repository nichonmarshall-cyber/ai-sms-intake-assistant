"""Regression coverage for combined Auto Repair vehicle answers."""

from unittest.mock import patch

from sqlalchemy import select

from modules.db import session_scope
from modules.intake_engine import extract_combined_vehicle_details
from modules.models import ConversationSession
from modules.profiles import PROFILES
from tests.conftest import fake_ai_result, send_sms


def test_combined_vehicle_parser_requires_a_direct_year_make_model_answer():
    profile = PROFILES["auto_repair"]

    assert extract_combined_vehicle_details(
        profile, "2005 Chevy Cobalt LS", expected_field_key="vehicle_year"
    ) == {
        "vehicle_year": "2005",
        "vehicle_make": "Chevy",
        "vehicle_model": "Cobalt LS",
    }
    assert extract_combined_vehicle_details(
        profile, "I drive a 2005 Chevy Cobalt LS", expected_field_key="vehicle_year"
    ) == {}
    assert extract_combined_vehicle_details(
        profile, "2005 Chevy Cobalt LS", expected_field_key="problem_description"
    ) == {}


def test_combined_vehicle_answer_advances_without_reasking_year(demo_app):
    phone = "+15557770001"
    profile = PROFILES["auto_repair"]

    send_sms(demo_app, phone, "DEMO")
    send_sms(demo_app, phone, "1")
    with patch(
        "modules.openai_helper.get_ai_response",
        return_value=fake_ai_result(
            profile,
            reply="Thanks, Nicholas. What year, make, and model is the vehicle?",
            extracted_fields={"customer_name": "Nicholas"},
        ),
    ):
        send_sms(demo_app, phone, "Nicholas")

    with patch("modules.openai_helper.get_ai_response") as mock_ai:
        _, reply = send_sms(demo_app, phone, "2005 Chevy Cobalt LS")

    mock_ai.assert_not_called()
    assert "Got it, a 2005 Chevy Cobalt LS." in reply
    assert "What's going on with the vehicle?" in reply
    assert "What year is the vehicle?" not in reply

    db = session_scope()
    try:
        session = db.execute(
            select(ConversationSession).where(ConversationSession.phone == phone)
        ).scalar_one()
        assert session.fields["vehicle_year"] == "2005"
        assert session.fields["vehicle_make"] == "Chevy"
        assert session.fields["vehicle_model"] == "Cobalt LS"
    finally:
        db.close()
