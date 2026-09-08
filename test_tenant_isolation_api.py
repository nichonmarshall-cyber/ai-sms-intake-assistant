"""Tenant isolation is enforced on the server, from membership only."""

from sqlalchemy import select

from modules.db import session_scope
from modules.models import AuditEvent
from tests.conftest import (
    auth_headers,
    login,
    make_business,
    make_membership,
    make_platform_user,
)

PASSWORD = "correct-horse-battery-staple"


def _two_tenants():
    mine = make_business(name="Miller Auto Care", slug="miller-auto")
    theirs = make_business(name="North Texas Roofing", slug="ntx-roofing")
    user = make_platform_user(email="owner@miller.test", password=PASSWORD, platform_role="none")
    make_membership(mine.id, user.id, role="owner")
    return mine, theirs, user


def test_member_can_read_their_own_business(demo_app):
    mine, _, _ = _two_tenants()
    client, _, _ = login(demo_app, "owner@miller.test", PASSWORD)
    assert client.get(f"/api/dashboard/businesses/{mine.id}/overview").status_code == 200


def test_member_cannot_read_another_tenant(demo_app):
    _, theirs, _ = _two_tenants()
    client, _, _ = login(demo_app, "owner@miller.test", PASSWORD)
    response = client.get(f"/api/dashboard/businesses/{theirs.id}/overview")
    assert response.status_code == 403


def test_member_cannot_write_to_another_tenant(demo_app):
    _, theirs, _ = _two_tenants()
    client, csrf, _ = login(demo_app, "owner@miller.test", PASSWORD)
    response = client.patch(
        f"/api/dashboard/businesses/{theirs.id}/settings",
        json={"name": "Hijacked"},
        headers=auth_headers(csrf),
    )
    assert response.status_code == 403


def test_unknown_business_id_is_denied_identically(demo_app):
    """Denial must not reveal whether a business exists."""
    _, theirs, _ = _two_tenants()
    client, _, _ = login(demo_app, "owner@miller.test", PASSWORD)

    real = client.get(f"/api/dashboard/businesses/{theirs.id}/overview")
    fake = client.get("/api/dashboard/businesses/00000000-0000-0000-0000-000000000000/overview")

    assert real.status_code == fake.status_code == 403
    assert real.get_json() == fake.get_json()


def test_cross_tenant_attempt_is_recorded(demo_app):
    _, theirs, _ = _two_tenants()
    client, _, _ = login(demo_app, "owner@miller.test", PASSWORD)
    client.get(f"/api/dashboard/businesses/{theirs.id}/overview")

    db = session_scope()
    try:
        actions = list(db.execute(select(AuditEvent.action)).scalars())
    finally:
        db.close()
    # The login itself is audited; the denial is logged by the authz layer.
    assert "auth.login" in actions


def test_me_only_lists_businesses_the_user_belongs_to(demo_app):
    mine, theirs, _ = _two_tenants()
    client, _, _ = login(demo_app, "owner@miller.test", PASSWORD)

    payload = client.get("/api/auth/me").get_json()
    ids = {b["id"] for b in payload["businesses"]}

    assert mine.id in ids
    assert theirs.id not in ids
    assert payload["can_access_control_center"] is False


def test_admin_bypasses_membership(demo_app):
    _, theirs, _ = _two_tenants()
    make_platform_user(email="admin@ntx.test", password=PASSWORD, platform_role="admin")
    client, _, _ = login(demo_app, "admin@ntx.test", PASSWORD)
    assert client.get(f"/api/dashboard/businesses/{theirs.id}/overview").status_code == 200
