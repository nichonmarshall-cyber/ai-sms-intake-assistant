"""Duplicate Twilio MessageSid must never re-run side effects or double-reply."""

from unittest.mock import patch

from tests.conftest import send_sms, fake_ai_result
from modules.profiles import PROFILES


def test_duplicate_message_sid_replays_identical_response_without_reprocessing(demo_app):
    phone = "+15556660001"
    code1, body1 = send_sms(demo_app, phone, "hi", sid="SM-DUPLICATE-1")
    code2, body2 = send_sms(demo_app, phone, "hi", sid="SM-DUPLICATE-1")

    assert code1 == 200 and code2 == 200
    assert body1 == body2

    from modules.db import session_scope
    from modules.models import ProcessedMessage
    from sqlalchemy import select

    db = session_scope()
    try:
        rows = db.execute(select(ProcessedMessage).where(ProcessedMessage.message_sid == "SM-DUPLICATE-1")).scalars().all()
        assert len(rows) == 1  # not duplicated
    finally:
        db.close()


def test_duplicate_message_sid_does_not_call_openai_twice(demo_app):
    phone = "+15556660002"
    send_sms(demo_app, phone, "hi")
    send_sms(demo_app, phone, "1")

    profile = PROFILES["auto_repair"]
    with patch("modules.openai_helper.get_ai_response", return_value=fake_ai_result(profile)) as mock_ai:
        send_sms(demo_app, phone, "answer one", sid="SM-DUP-2")
        assert mock_ai.call_count == 1
        send_sms(demo_app, phone, "answer one", sid="SM-DUP-2")
        assert mock_ai.call_count == 1  # retried delivery did not call OpenAI again
