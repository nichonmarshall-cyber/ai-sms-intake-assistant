from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import select

from modules.auth import passwords
from modules.db import session_scope
from modules.models import PasswordResetToken, PlatformUser, UserSession
from tests.conftest import auth_headers, login, make_platform_user


PASSWORD = "correct-horse-battery-staple"
NEW_PASSWORD = "a-new-long-private-passphrase"


def test_temporary_password_blocks_dashboard_until_changed(demo_app):
    user = make_platform_user(
        email="owner@client.test",
        password=PASSWORD,
        platform_role="none",
        must_change_password=True,
    )
    client, csrf, signed_in = login(demo_app, user.email, PASSWORD)
    assert signed_in.status_code == 200
    assert signed_in.get_json()["user"]["requires_credential_change"] is True

    blocked = client.get("/api/dashboard/businesses/anything/navigation")
    assert blocked.status_code == 403
    assert blocked.get_json()["code"] == "password_change_required"

    changed = client.post(
        "/api/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=auth_headers(csrf),
    )
    assert changed.status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert login(demo_app, user.email, PASSWORD)[2].status_code == 401
    assert login(demo_app, user.email, NEW_PASSWORD)[2].status_code == 200


def test_reset_request_is_enumeration_resistant_and_sends_one_time_link(demo_app):
    user = make_platform_user(email="owner@client.test", password=PASSWORD, platform_role="none")
    sent = {}

    def capture(*, recipient, token):
        sent.update(recipient=recipient, token=token)
        return True

    with patch("modules.web.auth_routes.mailer.send_password_reset", side_effect=capture):
        known = demo_app.app.test_client().post(
            "/api/auth/password-reset/request", json={"email": user.email}
        )
    unknown = demo_app.app.test_client().post(
        "/api/auth/password-reset/request", json={"email": "missing@client.test"}
    )
    assert known.status_code == unknown.status_code == 202
    assert known.get_json() == unknown.get_json()
    assert "token" not in str(known.get_json()).lower()
    assert sent["recipient"] == user.email

    reset = demo_app.app.test_client().post(
        "/api/auth/password-reset/confirm",
        json={"token": sent["token"], "new_password": NEW_PASSWORD},
    )
    assert reset.status_code == 200
    reused = demo_app.app.test_client().post(
        "/api/auth/password-reset/confirm",
        json={"token": sent["token"], "new_password": "another-very-long-passphrase"},
    )
    assert reused.status_code == 400
    assert login(demo_app, user.email, NEW_PASSWORD)[2].status_code == 200


def test_expired_reset_token_is_rejected(demo_app):
    user = make_platform_user(email="owner@client.test", password=PASSWORD, platform_role="none")
    sent = {}
    with patch(
        "modules.web.auth_routes.mailer.send_password_reset",
        side_effect=lambda **kwargs: sent.update(kwargs) or True,
    ):
        demo_app.app.test_client().post(
            "/api/auth/password-reset/request", json={"email": user.email}
        )
    db = session_scope()
    try:
        row = db.execute(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)).scalar_one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()
    response = demo_app.app.test_client().post(
        "/api/auth/password-reset/confirm",
        json={"token": sent["token"], "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 400


def test_admin_reset_forces_client_change_and_revokes_sessions(demo_app):
    admin = make_platform_user(email="admin@ntx.test", password=PASSWORD, platform_role="admin")
    client_user = make_platform_user(email="owner@client.test", password=PASSWORD, platform_role="none")
    victim_client, _, _ = login(demo_app, client_user.email, PASSWORD)
    admin_client, csrf, _ = login(demo_app, admin.email, PASSWORD)

    response = admin_client.post(
        f"/api/admin/users/{client_user.id}/reset-password",
        json={"password": NEW_PASSWORD},
        headers=auth_headers(csrf),
    )
    assert response.status_code == 200
    assert response.get_json()["requires_credential_change"] is True
    assert victim_client.get("/api/auth/me").status_code == 401

    db = session_scope()
    try:
        stored = db.get(PlatformUser, client_user.id)
        assert stored.must_change_password is True
        assert passwords.verify_password(stored.password_hash, NEW_PASSWORD)
        live = list(db.execute(select(UserSession).where(UserSession.user_id == client_user.id)).scalars())
        assert all(row.revoked_at is not None for row in live)
    finally:
        db.close()
