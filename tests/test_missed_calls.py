"""Missed-call Voice webhook rules and idempotency."""

from unittest.mock import patch

from sqlalchemy import select

from modules.db import session_scope
from modules.models import MissedCallEvent
from tests.conftest import send_sms


CALLER = "+15555550101"
TWILIO_NUMBER = "+18173936339"


def send_voice(app_module, *, caller: str = CALLER, call_sid: str = "CA-test-1"):
    return app_module.app.test_client().post(
        "/voice/missed-call",
        data={
            "From": caller,
            "To": TWILIO_NUMBER,
            "ForwardedFrom": "+15555550999",
            "CallSid": call_sid,
        },
    )


def get_events():
    db = session_scope()
    try:
        return db.execute(select(MissedCallEvent).order_by(MissedCallEvent.id)).scalars().all()
    finally:
        db.close()


def test_disabled_feature_records_call_without_sending(make_app):
    app_module = make_app(
        MISSED_CALLS_ENABLED="false",
        MISSED_CALL_REQUIRE_ALLOWLIST="true",
        MISSED_CALL_ALLOWLIST=CALLER,
    )

    with patch("modules.missed_call._send_initial_sms") as send_sms_mock:
        response = send_voice(app_module)

    assert response.status_code == 200
    assert "<Hangup" in response.get_data(as_text=True)
    send_sms_mock.assert_not_called()
    events = get_events()
    assert len(events) == 1
    assert events[0].decision == "feature_disabled"


def test_allowlisted_caller_receives_one_initial_text(make_app):
    app_module = make_app(
        MISSED_CALLS_ENABLED="true",
        MISSED_CALL_REQUIRE_ALLOWLIST="true",
        MISSED_CALL_ALLOWLIST=CALLER,
        MISSED_CALL_COOLDOWN_MINUTES="5",
    )

    with patch("modules.missed_call._send_initial_sms", return_value="SM-outbound-1") as send_sms_mock:
        response = send_voice(app_module)

    assert response.status_code == 200
    assert "We'll text you shortly" in response.get_data(as_text=True)
    send_sms_mock.assert_called_once()
    assert send_sms_mock.call_args.kwargs["caller_phone"] == CALLER
    assert send_sms_mock.call_args.kwargs["twilio_number"] == TWILIO_NUMBER
    assert "Reply STOP" in send_sms_mock.call_args.kwargs["body"]
    events = get_events()
    assert len(events) == 1
    assert events[0].decision == "sent"
    assert events[0].message_sid == "SM-outbound-1"


def test_non_allowlisted_caller_is_suppressed(make_app):
    app_module = make_app(
        MISSED_CALLS_ENABLED="true",
        MISSED_CALL_REQUIRE_ALLOWLIST="true",
        MISSED_CALL_ALLOWLIST="+15555550901",
    )

    with patch("modules.missed_call._send_initial_sms") as send_sms_mock:
        response = send_voice(app_module)

    assert response.status_code == 200
    send_sms_mock.assert_not_called()
    assert get_events()[0].decision == "caller_not_allowlisted"


def test_duplicate_callsid_never_sends_twice(make_app):
    app_module = make_app(
        MISSED_CALLS_ENABLED="true",
        MISSED_CALL_REQUIRE_ALLOWLIST="true",
        MISSED_CALL_ALLOWLIST=CALLER,
        MISSED_CALL_BLOCKLIST="",
    )

    with patch("modules.missed_call._send_initial_sms", return_value="SM-outbound-2") as send_sms_mock:
        first = send_voice(app_module, call_sid="CA-duplicate")
        second = send_voice(app_module, call_sid="CA-duplicate")

    assert first.status_code == 200 and second.status_code == 200
    assert send_sms_mock.call_count == 1
    events = get_events()
    assert len(events) == 1
    assert events[0].call_sid == "CA-duplicate"


def test_cooldown_suppresses_a_second_call_from_same_caller(make_app):
    app_module = make_app(
        MISSED_CALLS_ENABLED="true",
        MISSED_CALL_REQUIRE_ALLOWLIST="true",
        MISSED_CALL_ALLOWLIST=CALLER,
        MISSED_CALL_COOLDOWN_MINUTES="5",
    )

    with patch("modules.missed_call._send_initial_sms", return_value="SM-outbound-3") as send_sms_mock:
        send_voice(app_module, call_sid="CA-cooldown-1")
        send_voice(app_module, call_sid="CA-cooldown-2")

    assert send_sms_mock.call_count == 1
    events = get_events()
    assert [event.decision for event in events] == ["sent", "cooldown_active"]


def test_blocked_or_opted_out_caller_never_receives_initial_text(make_app):
    app_module = make_app(
        MISSED_CALLS_ENABLED="true",
        MISSED_CALL_REQUIRE_ALLOWLIST="true",
        MISSED_CALL_ALLOWLIST=CALLER,
        MISSED_CALL_BLOCKLIST=CALLER,
    )

    with patch("modules.missed_call._send_initial_sms") as send_sms_mock:
        send_voice(app_module, call_sid="CA-blocked")

    send_sms_mock.assert_not_called()
    assert get_events()[0].decision == "blocked_caller"

    # STOP remains the source of truth even when the caller is otherwise
    # eligible for missed-call follow-up.
    app_module = make_app(
        MISSED_CALLS_ENABLED="true",
        MISSED_CALL_REQUIRE_ALLOWLIST="true",
        MISSED_CALL_ALLOWLIST=CALLER,
        MISSED_CALL_BLOCKLIST="",
    )
    send_sms(app_module, CALLER, "STOP", sid="SM-opt-out")

    with patch("modules.missed_call._send_initial_sms") as send_sms_mock:
        send_voice(app_module, call_sid="CA-opted-out")

    send_sms_mock.assert_not_called()
    assert get_events()[0].decision == "caller_opted_out"
