"""CSRF is bound to the database session -- and Twilio routes stay exempt."""

from sqlalchemy import select

from modules.db import session_scope
from modules.models import UserSession
from tests.conftest import auth_headers, login, make_business, make_membership, make_platform_user, send_sms

PASSWORD = "correct-horse-battery-staple"


def test_mutating_request_without_csrf_header_is_rejected(demo_app):
    make_platform_user(email="admin@ntx.test", password=PASSWORD)
    client, _, _ = login(demo_app, "admin@ntx.test", PASSWORD)

    response = client.post("/api/auth/logout")
    assert response.status_code == 403
    assert "CSRF" in response.get_json()["error"]


def test_mutating_request_with_correct_csrf_header_succeeds(demo_app):
    make_platform_user(email="admin@ntx.test", password=PASSWORD)
    client, csrf, _ = login(demo_app, "admin@ntx.test", PASSWORD)
    assert client.post("/api/auth/logout", headers=auth_headers(csrf)).status_code == 200


def test_csrf_token_from_another_session_is_rejected(demo_app):
    """A readable cookie alone is not trusted; the token must match this session."""
    make_platform_user(email="a@ntx.test", password=PASSWORD)
    make_platform_user(email="b@ntx.test", password=PASSWORD)

    client_a, csrf_a, _ = login(demo_app, "a@ntx.test", PASSWORD)
    _, csrf_b, _ = login(demo_app, "b@ntx.test", PASSWORD)
    assert csrf_a != csrf_b

    response = client_a.post("/api/auth/logout", headers=auth_headers(csrf_b))
    assert response.status_code == 403


def test_csrf_hash_not_raw_token_is_stored(demo_app):
    make_platform_user(email="admin@ntx.test", password=PASSWORD)
    _, csrf, _ = login(demo_app, "admin@ntx.test", PASSWORD)

    db = session_scope()
    try:
        row = db.execute(select(UserSession)).scalar_one()
    finally:
        db.close()
    assert row.csrf_hash != csrf
    assert len(row.csrf_hash) == 64


def test_safe_methods_do_not_require_a_csrf_header(demo_app):
    make_platform_user(email="admin@ntx.test", password=PASSWORD)
    client, _, _ = login(demo_app, "admin@ntx.test", PASSWORD)
    assert client.get("/api/auth/me").status_code == 200


def test_twilio_sms_webhook_is_exempt_from_csrf(demo_app):
    """The single most important regression guard in this phase."""
    status, body = send_sms(demo_app, "+15125550123", "hello")
    assert status == 200
    assert "<Response>" in body


def test_twilio_voice_webhook_is_exempt_from_csrf(demo_app):
    client = demo_app.app.test_client()
    response = client.post(
        "/voice/missed-call",
        data={
            "From": "+15125550123",
            "To": "+18173936339",
            "CallSid": "CA-csrf-exempt-check",
        },
    )
    assert response.status_code == 200


def test_health_endpoint_still_open(demo_app):
    response = demo_app.app.test_client().get("/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"
