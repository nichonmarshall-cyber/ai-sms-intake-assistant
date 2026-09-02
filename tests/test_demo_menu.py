"""Demo mode: menu display, selection by number/name, invalid selection, MENU reset."""

import pytest

from tests.conftest import send_sms


def test_first_contact_shows_menu(demo_app):
    code, body = send_sms(demo_app, "+15550000001", "hi")
    assert code == 200
    assert "1 Auto Repair" in body
    assert "2 Roofing" in body
    assert "3 Painting" in body
    assert "4 Lawn Care" in body
    assert "5 Catering" in body
    assert "Demo only" in body


@pytest.mark.parametrize(
    "selection,expected_profile_key",
    [
        ("1", "auto_repair"),
        ("auto repair", "auto_repair"),
        ("2", "roofing"),
        ("Roofing", "roofing"),
        ("3", "painting"),
        ("painting", "painting"),
        ("4", "lawn_care"),
        ("lawn care", "lawn_care"),
        ("5", "catering"),
        ("catering", "catering"),
    ],
)
def test_selection_by_number_and_name(demo_app, selection, expected_profile_key):
    phone = "+15550000002"
    send_sms(demo_app, phone, "hi")  # menu
    code, body = send_sms(demo_app, phone, selection)
    assert code == 200

    from modules.db import session_scope
    from modules.conversation_store import normalize_phone
    from modules.models import ConversationSession
    from sqlalchemy import select

    db = session_scope()
    try:
        session = db.execute(
            select(ConversationSession).where(ConversationSession.phone == normalize_phone(phone))
        ).scalar_one()
        assert session.profile_key == expected_profile_key
        assert session.state == "in_progress"
    finally:
        db.close()


def test_invalid_selection_reshows_menu(demo_app):
    phone = "+15550000003"
    send_sms(demo_app, phone, "hi")
    code, body = send_sms(demo_app, phone, "banana")
    assert code == 200
    assert "1 Auto Repair" in body
    assert "catch that" in body.lower()  # apostrophe is XML-escaped as &apos; in the TwiML body


def test_menu_keyword_resets_mid_flow(demo_app):
    phone = "+15550000004"
    send_sms(demo_app, phone, "hi")
    send_sms(demo_app, phone, "1")  # now in_progress on auto_repair

    code, body = send_sms(demo_app, phone, "MENU")
    assert code == 200
    assert "1 Auto Repair" in body

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
        assert session.profile_key is None
        assert session.fields == {}
    finally:
        db.close()


def test_demo_keyword_also_resets(demo_app):
    phone = "+15550000005"
    send_sms(demo_app, phone, "hi")
    send_sms(demo_app, phone, "2")
    code, body = send_sms(demo_app, phone, "DEMO")
    assert "1 Auto Repair" in body
