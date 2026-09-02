"""OpenAI failure handling: safe fallback at the helper level, and graceful
degradation at the webhook level if something still slips through."""

from unittest.mock import patch, MagicMock

from tests.conftest import send_sms
from modules.profiles import PROFILES
from modules import openai_helper


def test_openai_client_exception_returns_safe_fallback():
    profile = PROFILES["auto_repair"]

    with patch.object(openai_helper, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("network down")
        mock_get_client.return_value = mock_client

        result = openai_helper.get_ai_response(
            [{"role": "user", "content": "hi"}],
            profile=profile,
            is_demo=True,
            is_business_hours=True,
            business_name="NTX Automation Co.",
            next_field=profile.fields[0],
        )

    assert result["should_terminate"] is True
    assert result["termination_reason"] == "error"
    assert result["reply"]
    assert set(result["extracted_fields"].keys()) == set(profile.field_keys())


def test_openai_invalid_json_returns_safe_fallback():
    profile = PROFILES["auto_repair"]

    with patch.object(openai_helper, "_get_client") as mock_get_client:
        mock_message = MagicMock()
        mock_message.content = "not valid json{{{"
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = openai_helper.get_ai_response(
            [{"role": "user", "content": "hi"}],
            profile=profile,
            is_demo=True,
            is_business_hours=True,
            business_name="NTX Automation Co.",
            next_field=profile.fields[0],
        )

    assert result["termination_reason"] == "error"


def test_webhook_survives_unexpected_exception_from_openai_helper(demo_app):
    phone = "+15558880001"
    send_sms(demo_app, phone, "hi")
    send_sms(demo_app, phone, "1")

    with patch("modules.openai_helper.get_ai_response", side_effect=RuntimeError("boom")):
        code, body = send_sms(demo_app, phone, "trigger the crash")

    assert code == 200
    assert "issue on our end" in body.lower()
