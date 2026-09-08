"""Login correctness, account enumeration resistance, and audit trail."""

from tests.conftest import login, make_platform_user

PASSWORD = "correct-horse-battery-staple"


def test_valid_login_sets_httponly_session_and_readable_csrf_cookie(demo_app):
    make_platform_user(email="admin@ntx.test", password=PASSWORD)

    _, csrf, response = login(demo_app, "admin@ntx.test", PASSWORD)

    assert response.status_code == 200
    assert csrf
    headers = "\n".join(response.headers.getlist("Set-Cookie"))
    assert "ntx_session=" in headers
    # The session cookie must never be readable by JavaScript.
    session_cookie = [h for h in response.headers.getlist("Set-Cookie") if h.startswith("ntx_session=")][0]
    assert "HttpOnly" in session_cookie
    assert "SameSite=Lax" in session_cookie
    # The CSRF cookie is readable on purpose so the SPA can echo it.
    csrf_cookie = [h for h in response.headers.getlist("Set-Cookie") if h.startswith("ntx_csrf=")][0]
    assert "HttpOnly" not in csrf_cookie


def test_login_response_never_leaks_password_hash(demo_app):
    make_platform_user(email="admin@ntx.test", password=PASSWORD)
    _, _, response = login(demo_app, "admin@ntx.test", PASSWORD)
    body = response.get_data(as_text=True)
    assert "password_hash" not in body
    assert "scrypt" not in body


def test_wrong_password_is_rejected(demo_app):
    make_platform_user(email="admin@ntx.test", password=PASSWORD)
    _, _, response = login(demo_app, "admin@ntx.test", "not-the-password")
    assert response.status_code == 401


def test_unknown_and_known_email_give_identical_failure_response(demo_app):
    make_platform_user(email="admin@ntx.test", password=PASSWORD)

    _, _, known = login(demo_app, "admin@ntx.test", "wrong-password-here")
    _, _, unknown = login(demo_app, "nobody@ntx.test", "wrong-password-here")

    assert known.status_code == unknown.status_code == 401
    assert known.get_json() == unknown.get_json()


def test_inactive_user_cannot_log_in(demo_app):
    make_platform_user(email="gone@ntx.test", password=PASSWORD, is_active=False)
    _, _, response = login(demo_app, "gone@ntx.test", PASSWORD)
    assert response.status_code == 401


def test_login_writes_an_audit_event(demo_app):
    from sqlalchemy import select

    from modules.db import session_scope
    from modules.models import AuditEvent

    make_platform_user(email="admin@ntx.test", password=PASSWORD)
    login(demo_app, "admin@ntx.test", PASSWORD)

    db = session_scope()
    try:
        actions = list(db.execute(select(AuditEvent.action)).scalars())
    finally:
        db.close()
    assert "auth.login" in actions


def test_ip_address_is_never_stored_in_plaintext(demo_app):
    from sqlalchemy import select

    from modules.db import session_scope
    from modules.models import LoginAttempt, UserSession

    make_platform_user(email="admin@ntx.test", password=PASSWORD)
    client = demo_app.app.test_client()
    client.post(
        "/api/auth/login",
        json={"email": "admin@ntx.test", "password": PASSWORD},
        headers={"X-Forwarded-For": "203.0.113.42"},
    )

    db = session_scope()
    try:
        attempt_hashes = list(db.execute(select(LoginAttempt.ip_hash)).scalars())
        session_hashes = list(db.execute(select(UserSession.ip_hash)).scalars())
    finally:
        db.close()

    assert attempt_hashes and all(h != "203.0.113.42" for h in attempt_hashes)
    assert session_hashes and all(h != "203.0.113.42" for h in session_hashes)
    assert all(len(h) == 64 for h in session_hashes if h)
