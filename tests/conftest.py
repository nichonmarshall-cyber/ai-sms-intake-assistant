"""
conftest.py
Shared pytest fixtures.

Each test that needs a running Flask app gets a fully isolated process
configuration: its own SQLite file (never shared between tests), its own
reloaded `app` module (so APP_MODE / DEFAULT_PROFILE take effect), and
Twilio signature validation bypassed by default (individual tests that
need real signature validation override that explicitly).

No real OpenAI, Twilio, or Google API calls are ever made in the suite --
tests either mock modules.openai_helper.get_ai_response directly, or use
TWILIO_VALIDATION_BYPASS / SHEETS_ENABLED=false so nothing outbound fires.
"""

import importlib
import os
import uuid

import pytest

import modules.db as db_module


DEFAULT_ENV = {
    "APP_MODE": "demo",
    "OPENAI_API_KEY": "test-key",
    "TWILIO_ACCOUNT_SID": "test-sid",
    "TWILIO_AUTH_TOKEN": "test-auth-token",
    "TWILIO_VALIDATION_BYPASS": "true",
    "SESSION_TTL_MINUTES": "45",
    "FLASK_ENV": "development",
    "SHEETS_ENABLED": "false",
    "MAX_TURNS": "15",
}

# Env keys that must be explicitly cleared between tests if not re-set,
# since monkeypatch.setenv from a previous test in the same session could
# otherwise leak into a test that expects them unset.
_OPTIONAL_KEYS = (
    "DEFAULT_PROFILE",
    "ENABLED_PROFILES",
    "PUBLIC_BASE_URL",
    "TENANT_ROUTING_ENABLED",
)


@pytest.fixture
def make_app(tmp_path, monkeypatch):
    """
    Returns a factory: make_app(**env_overrides) -> freshly reloaded `app`
    module, configured per the given environment and backed by a brand
    new SQLite file unique to this test.
    """

    def _make(**overrides):
        db_path = tmp_path / f"test_{uuid.uuid4().hex}.db"
        env = dict(DEFAULT_ENV)
        env["DATABASE_URL"] = f"sqlite:///{db_path}"
        env.update(overrides)

        for key in _OPTIONAL_KEYS:
            if key not in env:
                monkeypatch.delenv(key, raising=False)

        for key, value in env.items():
            monkeypatch.setenv(key, value)

        # Force db.py to rebuild its engine/session factory against the
        # new DATABASE_URL instead of reusing a previous test's engine.
        db_module._engine = None
        db_module._SessionLocal = None

        import app as app_module
        importlib.reload(app_module)
        return app_module

    return _make


@pytest.fixture
def demo_app(make_app):
    return make_app(APP_MODE="demo")


def send_sms(
    app_module,
    phone: str,
    body: str,
    sid: str | None = None,
    to_number: str = "+18173936339",
):
    """POSTs one inbound SMS through the Flask test client and returns (status_code, text)."""
    client = app_module.app.test_client()
    data = {"From": phone, "To": to_number, "Body": body}
    if sid:
        data["MessageSid"] = sid
    else:
        data["MessageSid"] = f"SM{uuid.uuid4().hex}"
    resp = client.post("/sms", data=data)
    return resp.status_code, resp.get_data(as_text=True)


def fake_ai_result(profile, **overrides) -> dict:
    """Builds a minimal valid AI response dict scoped to a profile's field schema."""
    result = {
        "reply": "Thanks, got it.",
        "category": profile.categories[0],
        "extracted_fields": {f.key: None for f in profile.fields},
        "is_complete": False,
        "business_summary": None,
        "topic_status": "on_topic",
        "should_terminate": False,
        "termination_reason": None,
    }
    result.update(overrides)
    return result


# ---------------------------------------------------------------------------
# Dashboard auth helpers (Phase 1a)
# ---------------------------------------------------------------------------

def make_platform_user(
    email: str = "admin@ntx.test",
    password: str = "correct-horse-battery-staple",
    platform_role: str = "admin",
    is_active: bool = True,
):
    """Creates a dashboard user directly in the test database."""
    from modules.auth import passwords
    from modules.db import session_scope
    from modules.models import PlatformUser

    db = session_scope()
    try:
        user = PlatformUser(
            id=str(uuid.uuid4()),
            email=email.lower(),
            display_name=email.split("@")[0],
            password_hash=passwords.hash_password(password),
            platform_role=platform_role,
            is_platform_admin=(platform_role == "admin"),
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def make_business(name: str = "Miller Auto Care", slug: str = "miller-auto", with_defaults: bool = True):
    from modules import entitlements
    from modules.db import session_scope
    from modules.models import Business

    db = session_scope()
    try:
        business = Business(
            id=str(uuid.uuid4()), name=name, slug=slug, status="active", settings={}
        )
        db.add(business)
        db.flush()
        if with_defaults:
            entitlements.apply_defaults(db, business.id)
        db.commit()
        db.refresh(business)
        return business
    finally:
        db.close()


def make_membership(business_id: str, user_id: str, role: str = "owner"):
    from modules.db import session_scope
    from modules.models import BusinessMembership

    db = session_scope()
    try:
        membership = BusinessMembership(business_id=business_id, user_id=user_id, role=role)
        db.add(membership)
        db.commit()
        db.refresh(membership)
        return membership
    finally:
        db.close()


def _cookies_from(response) -> dict:
    jar = {}
    for header in response.headers.getlist("Set-Cookie"):
        name, _, rest = header.partition("=")
        jar[name.strip()] = rest.split(";")[0]
    return jar


def login(app_module, email: str, password: str):
    """Logs in and returns (client, csrf_token, response)."""
    client = app_module.app.test_client()
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    csrf = _cookies_from(response).get("ntx_csrf", "")
    return client, csrf, response


def auth_headers(csrf_token: str) -> dict:
    return {"X-CSRF-Token": csrf_token}
