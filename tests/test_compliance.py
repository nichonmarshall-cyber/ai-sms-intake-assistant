"""STOP/START/HELP compliance keywords are handled before the menu or LLM."""

from unittest.mock import patch

from tests.conftest import send_sms


def test_stop_opts_out_and_never_reaches_openai(demo_app):
    phone = "+15551230001"
    with patch("modules.openai_helper.get_ai_response") as mock_ai:
        code, body = send_sms(demo_app, phone, "STOP")
        assert code == 200
        assert "unsubscribed" in body.lower()
        mock_ai.assert_not_called()


def test_messages_after_stop_are_silenced(demo_app):
    phone = "+15551230002"
    send_sms(demo_app, phone, "STOP")

    with patch("modules.openai_helper.get_ai_response") as mock_ai:
        code, body = send_sms(demo_app, phone, "hello?")
        assert code == 204
        assert body == ""
        mock_ai.assert_not_called()


def test_start_opts_back_in_and_shows_menu(demo_app):
    phone = "+15551230003"
    send_sms(demo_app, phone, "STOP")

    code, body = send_sms(demo_app, phone, "START")
    assert code == 200
    assert "1 Auto Repair" in body


def test_help_replies_without_touching_session_state(demo_app):
    phone = "+15551230004"
    send_sms(demo_app, phone, "hi")  # menu shown, still awaiting selection

    code, body = send_sms(demo_app, phone, "HELP")
    assert code == 200
    assert "NTX Automation Co." in body

    from modules.db import session_scope
    from modules.conversation_store import normalize_phone
    from modules.models import ConversationSession
    from sqlalchemy import select

    db = session_scope()
    try:
        session = db.execute(
            select(ConversationSession).where(ConversationSession.phone == normalize_phone(phone))
        ).scalar_one()
        assert session.state == "awaiting_profile_selection"  # unchanged by HELP
    finally:
        db.close()


def test_stop_keyword_variants(demo_app):
    for i, keyword in enumerate(["stop", "STOPALL", "unsubscribe", "cancel", "end", "quit"]):
        phone = f"+1555999{i:04d}"
        code, body = send_sms(demo_app, phone, keyword)
        assert code == 200
        assert "unsubscribed" in body.lower()
