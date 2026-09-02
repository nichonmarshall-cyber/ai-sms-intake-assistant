"""Demo vs production mode separation, and startup validation."""

import pytest

from tests.conftest import send_sms
from modules.app_mode import AppModeConfigError


def test_demo_mode_shows_menu(demo_app):
    code, body = send_sms(demo_app, "+15554440001", "hi")
    assert "1 Auto Repair" in body


def test_production_mode_never_shows_menu(make_app):
    app_module = make_app(APP_MODE="production", DEFAULT_PROFILE="roofing")
    code, body = send_sms(app_module, "+15554440002", "hi")
    assert code == 200
    assert "1 Auto Repair" not in body
    assert "Choose:" not in body


def test_production_mode_locks_to_default_profile(make_app):
    app_module = make_app(APP_MODE="production", DEFAULT_PROFILE="roofing")
    assert app_module.APP_CONFIG.is_production
    assert app_module.APP_CONFIG.default_profile_key == "roofing"
    assert app_module.APP_CONFIG.enabled_profile_keys == ["roofing"]


def test_production_mode_refuses_to_start_without_default_profile(make_app):
    with pytest.raises(AppModeConfigError):
        make_app(APP_MODE="production")


def test_production_mode_refuses_invalid_default_profile(make_app):
    with pytest.raises(AppModeConfigError):
        make_app(APP_MODE="production", DEFAULT_PROFILE="not_a_real_profile")


def test_invalid_app_mode_rejected(make_app):
    with pytest.raises(AppModeConfigError):
        make_app(APP_MODE="not_a_real_mode")


def test_mechanic_alias_resolves_to_auto_repair_in_production(make_app):
    app_module = make_app(APP_MODE="production", DEFAULT_PROFILE="mechanic")
    assert app_module.APP_CONFIG.default_profile_key == "auto_repair"


def test_signature_bypass_forbidden_in_deployed_environment(make_app):
    # FLASK_ENV=production is the real "this is live infrastructure" signal;
    # the bypass must never be allowed there, regardless of APP_MODE.
    with pytest.raises(AppModeConfigError):
        make_app(APP_MODE="demo", TWILIO_VALIDATION_BYPASS="true", FLASK_ENV="production")
