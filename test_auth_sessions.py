"""Server-side session lifecycle: revocation, expiry, and write throttling."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from modules.db import session_scope
from modules.models import UserSession
from tests.conftest import auth_headers, login, make_platform_user

PASSWORD = "correct-horse-battery-staple"


def _only_session():
    db = session_scope()
    try:
        return db.execute(select(UserSession)).scalar_one()
    finally:
        db.close()


def test_authenticated_request_succeeds(demo_app):
    make_platform_user(email="admin@ntx.test", password=PASSWORD)
    client, _, _ = login(demo_app, "admin@ntx.test", PASSWORD)
    assert client.get("/api/auth/me").status_code == 200


def test_request_without_session_cookie_is_rejected(demo_app):
    make_platform_user(email="admin@ntx.test", password=PASSWORD)
    client = demo_app.app.test_client()
    assert client.get("/api/auth/me").status_code == 401


def test_only_a_hash_of_the_session_token_is_stored(demo_app):
    make_platform_user(email="admin@ntx.test", password=PASSWORD)
    client, _, response = login(demo_app, "admin@ntx.test", PASSWORD)
    raw_token = [
        h.split("=", 1)[1].split(";")[0]
        for h in response.headers.getlist("Set-Cookie")
        if h.startswith("ntx_session=")
    ][0]

    row = _only_session()
    assert row.token_hash != raw_token
    assert len(row.token_hash) == 64


def test_revoked_session_fails_on_the_very_next_request(demo_app):
    make_platform_user(email="admin@ntx.test", password=PASSWORD)
    client, csrf, _ = login(demo_app, "admin@ntx.test", PASSWORD)
    assert client.get("/api/auth/me").status_code == 200

    db = session_scope()
    try:
        db.execute(update(UserSession).values(revoked_at=datetime.now(timezone.utc)))
        db.commit()
    finally:
        db.close()

    assert client.get("/api/auth/me").status_code == 401


def test_expired_session_is_rejected(demo_app):
    make_platform_user(email="admin@ntx.test", password=PASSWORD)
    client, _, _ = login(demo_app, "admin@ntx.test", PASSWORD)

    db = session_scope()
    try:
        db.execute(
            update(UserSession).values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        db.commit()
    finally:
        db.close()

    assert client.get("/api/auth/me").status_code == 401


def test_idle_session_beyond_timeout_is_rejected(demo_app):
    make_platform_user(email="admin@ntx.test", password=PASSWORD)
    client, _, _ = login(demo_app, "admin@ntx.test", PASSWORD)

    db = session_scope()
    try:
        db.execute(
            update(UserSession).values(
                last_activity_at=datetime.now(timezone.utc) - timedelta(hours=13)
            )
        )
        db.commit()
    finally:
        db.close()

    assert client.get("/api/auth/me").status_code == 401


def test_last_activity_is_not_rewritten_on_every_request(demo_app):
    """Ordinary dashboard browsing must not turn every GET into a DB write."""
    make_platform_user(email="admin@ntx.test", password=PASSWORD)
    client, _, _ = login(demo_app, "admin@ntx.test", PASSWORD)

    first = _only_session().last_activity_at
    for _ in range(5):
        client.get("/api/auth/me")
    assert _only_session().last_activity_at == first


def test_last_activity_refreshes_once_the_interval_has_passed(demo_app):
    make_platform_user(email="admin@ntx.test", password=PASSWORD)
    client, _, _ = login(demo_app, "admin@ntx.test", PASSWORD)

    stale = datetime.now(timezone.utc) - timedelta(minutes=10)
    db = session_scope()
    try:
        db.execute(update(UserSession).values(last_activity_at=stale))
        db.commit()
    finally:
        db.close()

    client.get("/api/auth/me")
    refreshed = _only_session().last_activity_at
    assert refreshed.replace(tzinfo=timezone.utc) > stale


def test_logout_revokes_the_session_and_clears_cookies(demo_app):
    make_platform_user(email="admin@ntx.test", password=PASSWORD)
    client, csrf, _ = login(demo_app, "admin@ntx.test", PASSWORD)

    response = client.post("/api/auth/logout", headers=auth_headers(csrf))
    assert response.status_code == 200
    assert _only_session().revoked_at is not None
    assert client.get("/api/auth/me").status_code == 401


def test_retention_sweep_deletes_old_rows(demo_app):
    from modules.auth.sessions import purge_expired
    from modules.models import LoginAttempt

    make_platform_user(email="admin@ntx.test", password=PASSWORD)
    login(demo_app, "admin@ntx.test", PASSWORD)

    db = session_scope()
    try:
        db.execute(
            update(UserSession).values(
                revoked_at=datetime.now(timezone.utc) - timedelta(days=60),
                expires_at=datetime.now(timezone.utc) - timedelta(days=60),
            )
        )
        db.add(
            LoginAttempt(
                email_lower="old@ntx.test",
                ip_hash=None,
                success=False,
                created_at=datetime.now(timezone.utc) - timedelta(days=90),
            )
        )
        db.commit()
        result = purge_expired(db)
    finally:
        db.close()

    assert result["login_attempts"] >= 1
    assert result["expired_sessions"] + result["revoked_sessions"] >= 1
