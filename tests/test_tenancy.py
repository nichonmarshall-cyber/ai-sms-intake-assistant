from modules.models import Business, BusinessPhoneNumber
from modules.tenancy import DEFAULT_BUSINESS_SETTINGS, effective_settings


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
    assert settings["missed_calls"] == {"enabled": True, "cooldown_minutes": 15}
    assert DEFAULT_BUSINESS_SETTINGS["missed_calls"]["cooldown_minutes"] == 1440
