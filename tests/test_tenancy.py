from sqlalchemy import select

from modules.db import session_scope
from modules.models import Business, BusinessPhoneNumber, ConversationSession
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
