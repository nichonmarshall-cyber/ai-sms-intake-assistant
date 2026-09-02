"""Off-topic strike tracking, and the demo-only completion disclaimer."""

from unittest.mock import patch

from tests.conftest import send_sms, fake_ai_result
from modules.profiles import PROFILES


def _select_profile(app_module, phone, key="1"):
    send_sms(app_module, phone, "hi")
    send_sms(app_module, phone, key)


def _get_session(phone):
    from modules.db import session_scope
    from modules.conversation_store import normalize_phone
    from modules.models import ConversationSession
    from sqlalchemy import select

    db = session_scope()
    try:
        return db.execute(
            select(ConversationSession).where(ConversationSession.phone == normalize_phone(phone))
        ).scalar_one()
    finally:
        db.close()


def test_off_topic_strike_increments_then_resets(demo_app):
    phone = "+15553330001"
    _select_profile(demo_app, phone)
    profile = PROFILES["auto_repair"]

    with patch("modules.openai_helper.get_ai_response", return_value=fake_ai_result(profile, topic_status="off_topic")):
        send_sms(demo_app, phone, "tell me a joke")
    assert _get_session(phone).off_topic_strikes == 1

    with patch("modules.openai_helper.get_ai_response", return_value=fake_ai_result(profile, topic_status="on_topic")):
        send_sms(demo_app, phone, "ok back to my car")
    assert _get_session(phone).off_topic_strikes == 0


def test_second_off_topic_strike_can_terminate(demo_app):
    phone = "+15553330002"
    _select_profile(demo_app, phone)
    profile = PROFILES["auto_repair"]

    with patch("modules.openai_helper.get_ai_response", return_value=fake_ai_result(profile, topic_status="off_topic")):
        send_sms(demo_app, phone, "off topic 1")

    with patch(
        "modules.openai_helper.get_ai_response",
        return_value=fake_ai_result(
            profile, topic_status="off_topic", should_terminate=True, termination_reason="off_topic",
        ),
    ):
        send_sms(demo_app, phone, "off topic 2")

    session = _get_session(phone)
    assert session.terminated is True


def test_completion_reply_includes_demo_disclaimer(demo_app):
    phone = "+15553330003"
    _select_profile(demo_app, phone)
    profile = PROFILES["auto_repair"]

    complete_fields = {f.key: "answer" for f in profile.fields}

    from modules.db import session_scope
    from modules.conversation_store import normalize_phone, get_or_create_session
    from modules.models import ConversationSession
    from sqlalchemy import select

    # Pre-fill all but the last field so the final answer completes intake.
    db = session_scope()
    try:
        session = db.execute(
            select(ConversationSession).where(ConversationSession.phone == normalize_phone(phone))
        ).scalar_one()
        pre_filled = dict(complete_fields)
        last_key = profile.required_field_keys()[-1]
        pre_filled[last_key] = None
        session.fields = pre_filled
        db.add(session)
        db.commit()
    finally:
        db.close()

    with patch(
        "modules.openai_helper.get_ai_response",
        return_value=fake_ai_result(
            profile,
            extracted_fields=complete_fields,
            is_complete=True,
            should_terminate=True,
            termination_reason="completed",
            reply="Thanks, that's everything we need!",
        ),
    ):
        code, body = send_sms(demo_app, phone, "final answer")

    assert code == 200
    assert "demo" in body.lower()

    session = _get_session(phone)
    assert session.terminated is True

    from modules.models import Lead

    db = session_scope()
    try:
        lead = db.execute(select(Lead).where(Lead.phone == normalize_phone(phone))).scalar_one()
        assert lead.status == "completed"
    finally:
        db.close()


def test_premature_completion_claim_is_rejected(demo_app):
    """
    If the model claims should_terminate/completed but required fields are
    still missing, application code must not honor it (safety net).
    """
    phone = "+15553330004"
    _select_profile(demo_app, phone)
    profile = PROFILES["auto_repair"]

    with patch(
        "modules.openai_helper.get_ai_response",
        return_value=fake_ai_result(
            profile,
            is_complete=True,
            should_terminate=True,
            termination_reason="completed",
            reply="All done!",
        ),
    ):
        send_sms(demo_app, phone, "just my name is Bob")

    session = _get_session(phone)
    assert session.terminated is False


def test_application_forces_completion_when_final_field_is_collected(demo_app):
    """A complete intake closes even when the model forgets completion flags."""
    phone = "+15553330005"
    _select_profile(demo_app, phone)
    profile = PROFILES["auto_repair"]
    complete_fields = {f.key: "answer" for f in profile.fields}
    complete_fields["customer_name"] = "Nicholas"
    complete_fields["preferred_callback_time"] = "5pm"

    with patch(
        "modules.openai_helper.get_ai_response",
        return_value=fake_ai_result(
            profile,
            extracted_fields=complete_fields,
            is_complete=False,
            should_terminate=False,
            termination_reason=None,
            reply="We've noted that the best time is 5pm.",
        ),
    ):
        code, body = send_sms(demo_app, phone, "5pm")

    assert code == 200
    assert "Thanks, Nicholas" in body
    assert "5pm" in body
    assert "demo" in body.lower()
    assert _get_session(phone).terminated is True


def test_pricing_followup_after_completion_does_not_restart_menu(demo_app):
    phone = "+15553330006"
    _select_profile(demo_app, phone)
    profile = PROFILES["auto_repair"]
    complete_fields = {f.key: "answer" for f in profile.fields}

    with patch(
        "modules.openai_helper.get_ai_response",
        return_value=fake_ai_result(profile, extracted_fields=complete_fields),
    ):
        send_sms(demo_app, phone, "final answer")

    code, body = send_sms(demo_app, phone, "How much would this cost?")

    assert code == 200
    assert "Pricing depends on the job" in body
    assert "live setup" in body
    assert "Choose: 1 Auto Repair" not in body
