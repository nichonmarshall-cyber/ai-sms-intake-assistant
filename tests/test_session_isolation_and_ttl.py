"""Session isolation between phone numbers, and 45-minute TTL expiration."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import freezegun

from tests.conftest import send_sms, fake_ai_result
from modules.profiles import PROFILES


def test_two_phone_numbers_are_isolated(demo_app):
    phone_a = "+15551110001"
    phone_b = "+15551110002"

    send_sms(demo_app, phone_a, "hi")
    send_sms(demo_app, phone_a, "1")  # A picks Auto Repair

    send_sms(demo_app, phone_b, "hi")
    code, body = send_sms(demo_app, phone_b, "2")  # B picks Roofing independently

    from modules.db import session_scope
    from modules.conversation_store import normalize_phone
    from modules.models import ConversationSession
    from sqlalchemy import select

    db = session_scope()
    try:
        session_a = db.execute(
            select(ConversationSession).where(ConversationSession.phone == normalize_phone(phone_a))
        ).scalar_one()
        session_b = db.execute(
            select(ConversationSession).where(ConversationSession.phone == normalize_phone(phone_b))
        ).scalar_one()
        assert session_a.profile_key == "auto_repair"
        assert session_b.profile_key == "roofing"
    finally:
        db.close()


def test_session_expires_after_ttl_and_next_message_starts_fresh(make_app):
    app_module = make_app(APP_MODE="demo", SESSION_TTL_MINUTES="45")
    phone = "+15551110003"

    with freezegun.freeze_time("2026-01-01 12:00:00") as frozen:
        send_sms(app_module, phone, "hi")
        send_sms(app_module, phone, "1")  # in_progress, auto_repair selected

        profile = PROFILES["auto_repair"]
        with patch(
            "modules.openai_helper.get_ai_response",
            return_value=fake_ai_result(profile, extracted_fields={
                **{f.key: None for f in profile.fields}, "customer_name": "Alex",
            }),
        ):
            send_sms(app_module, phone, "my name is Alex")

        # Advance 46 minutes -- past the 45-minute TTL
        frozen.move_to("2026-01-01 12:46:01")

        code, body = send_sms(app_module, phone, "hello again")
        assert code == 200
        assert "1 Auto Repair" in body  # fresh demo -- back to the menu

    from modules.db import session_scope
    from modules.conversation_store import normalize_phone
    from modules.models import ConversationSession
    from sqlalchemy import select

    db = session_scope()
    try:
        session = db.execute(
            select(ConversationSession).where(ConversationSession.phone == normalize_phone(phone))
        ).scalar_one()
        assert session.state == "awaiting_profile_selection"
        assert session.fields == {}
    finally:
        db.close()


def test_session_survives_within_ttl(make_app):
    app_module = make_app(APP_MODE="demo", SESSION_TTL_MINUTES="45")
    phone = "+15551110004"

    with freezegun.freeze_time("2026-01-01 12:00:00") as frozen:
        send_sms(app_module, phone, "hi")
        send_sms(app_module, phone, "1")

        frozen.move_to("2026-01-01 12:30:00")  # 30 min later, still within TTL

        from modules.db import session_scope
        from modules.conversation_store import normalize_phone
        from modules.models import ConversationSession
        from sqlalchemy import select

        db = session_scope()
        try:
            session = db.execute(
                select(ConversationSession).where(ConversationSession.phone == normalize_phone(phone))
            ).scalar_one()
            assert session.state == "in_progress"
            assert session.profile_key == "auto_repair"
        finally:
            db.close()
