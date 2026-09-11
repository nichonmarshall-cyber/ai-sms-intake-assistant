from unittest.mock import patch

from sqlalchemy import select

from modules.db import session_scope
from modules.models import Business, BusinessPhoneNumber, ConversationSession, MissedCallEvent
from modules.tenancy import (
    DEFAULT_BUSINESS_SETTINGS,
    assign_phone_number,
    create_business,
    effective_settings,
)
from tests.conftest import send_sms


def test_phone_settings_override_business_without_losing_global_defaults():
    business = Business(
        id="business-a",
        name="A Auto",
        slug="a-auto",
        settings={
            "intake": {"enabled_profiles": ["auto_repair"], "demo_mode": False},
            "missed_calls": {"enabled": True, "cooldown_minutes": 60},
        },
    )
    number = BusinessPhoneNumber(
        business_id="business-a",
        phone="+18175550101",
        settings={"missed_calls": {"cooldown_minutes": 15}},
    )

    settings = effective_settings(business, number)

    assert settings["intake"]["enabled_profiles"] == ["auto_repair"]
    assert settings["intake"]["demo_mode"] is False
    assert settings["missed_calls"]["enabled"] is True
    assert settings["missed_calls"]["cooldown_minutes"] == 15
    assert settings["missed_calls"]["require_allowlist"] is False
    assert settings["missed_calls"]["max_send_attempts"] == 2
    assert DEFAULT_BUSINESS_SETTINGS["missed_calls"]["cooldown_minutes"] == 1440


def test_same_customer_phone_is_isolated_between_businesses(make_app):
    app_module = make_app(TENANT_ROUTING_ENABLED="true")
    db = session_scope()
    try:
        auto = create_business(
            db,
            name="A Auto",
            slug="a-auto",
            default_profile_key="auto_repair",
            settings={"intake": {"selection_mode": "single"}},
        )
        roof = create_business(
            db,
            name="B Roofing",
            slug="b-roofing",
            default_profile_key="roofing",
            settings={"intake": {"selection_mode": "single"}},
        )
        assign_phone_number(db, business_id=auto.id, phone="+18175550101")
        assign_phone_number(db, business_id=roof.id, phone="+18175550102")
        db.commit()
        auto_id, roof_id = auto.id, roof.id
    finally:
        db.close()

    customer = "+15557770123"
    assert send_sms(app_module, customer, "hello", to_number="+18175550101")[0] == 200
    assert send_sms(app_module, customer, "hello", to_number="+18175550102")[0] == 200

    db = session_scope()
    try:
        sessions = db.execute(
            select(ConversationSession).where(ConversationSession.phone == customer)
        ).scalars().all()
        assert {(session.business_id, session.profile_key) for session in sessions} == {
            (auto_id, "auto_repair"),
            (roof_id, "roofing"),
        }
    finally:
        db.close()


def test_unmapped_twilio_number_is_rejected_before_session_creation(make_app):
    app_module = make_app(TENANT_ROUTING_ENABLED="true")
    response = send_sms(
        app_module,
        "+15557770124",
        "hello",
        to_number="+18175559999",
    )
    assert response == (204, "")

    db = session_scope()
    try:
        assert db.execute(select(ConversationSession)).scalars().all() == []
    finally:
        db.close()


def test_missed_call_cooldown_is_isolated_between_tenants(make_app):
    app_module = make_app(TENANT_ROUTING_ENABLED="true")
    db = session_scope()
    try:
        settings = {
            "intake": {"selection_mode": "single"},
            "missed_calls": {
                "enabled": True,
                "require_allowlist": False,
                "cooldown_minutes": 1440,
            },
        }
        auto = create_business(
            db,
            name="A Auto",
            slug="voice-auto",
            default_profile_key="auto_repair",
            settings=settings,
        )
        roof = create_business(
            db,
            name="B Roofing",
            slug="voice-roofing",
            default_profile_key="roofing",
            settings=settings,
        )
        assign_phone_number(db, business_id=auto.id, phone="+18175550111")
        assign_phone_number(db, business_id=roof.id, phone="+18175550112")
        db.commit()
        business_ids = {auto.id, roof.id}
    finally:
        db.close()

    client = app_module.app.test_client()
    caller = "+15557770125"
    with patch(
        "modules.missed_call._send_initial_sms",
        side_effect=["SM-tenant-auto", "SM-tenant-roof"],
    ) as send_sms_mock:
        for index, destination in enumerate(("+18175550111", "+18175550112"), start=1):
            response = client.post(
                "/voice/missed-call",
                data={"From": caller, "To": destination, "CallSid": f"CA-tenant-{index}"},
            )
            assert response.status_code == 200

    assert send_sms_mock.call_count == 2
    db = session_scope()
    try:
        events = list(db.execute(select(MissedCallEvent)).scalars())
        assert {event.business_id for event in events} == business_ids
        assert {event.decision for event in events} == {"sent"}
    finally:
        db.close()


def test_unmapped_voice_destination_never_records_or_sends(make_app):
    app_module = make_app(TENANT_ROUTING_ENABLED="true")
    with patch("modules.missed_call._send_initial_sms") as send_sms_mock:
        response = app_module.app.test_client().post(
            "/voice/missed-call",
            data={
                "From": "+15557770126",
                "To": "+18175559999",
                "CallSid": "CA-unmapped-voice",
            },
        )

    assert response.status_code == 200
    send_sms_mock.assert_not_called()
    db = session_scope()
    try:
        assert list(db.execute(select(MissedCallEvent)).scalars()) == []
    finally:
        db.close()
