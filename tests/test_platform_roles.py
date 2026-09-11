"""Platform admin vs platform staff vs client user."""

from tests.conftest import (
    auth_headers,
    login,
    make_business,
    make_membership,
    make_platform_user,
)

PASSWORD = "correct-horse-battery-staple"


def test_admin_reaches_control_center_routes(demo_app):
    make_platform_user(email="admin@ntx.test", password=PASSWORD, platform_role="admin")
    client, _, _ = login(demo_app, "admin@ntx.test", PASSWORD)
    assert client.get("/api/admin/businesses").status_code == 200


def test_platform_staff_gets_read_only_control_center_access(demo_app):
    make_platform_user(email="staff@ntx.test", password=PASSWORD, platform_role="staff")
    client, csrf, _ = login(demo_app, "staff@ntx.test", PASSWORD)

    assert client.get("/api/admin/businesses").status_code == 200
    assert client.get("/api/admin/users").status_code == 200
    assert client.get("/api/admin/audit-events").status_code == 200
    assert client.get("/api/admin/conversations").status_code == 200
    assert client.get("/api/admin/delivery").status_code == 200
    assert client.get("/api/admin/webhooks").status_code == 200
    assert client.post(
        "/api/admin/businesses",
        json={"name": "Blocked", "slug": "blocked"},
        headers=auth_headers(csrf),
    ).status_code == 403


def test_platform_staff_gets_read_only_cross_tenant_access(demo_app):
    business = make_business()
    make_platform_user(email="staff@ntx.test", password=PASSWORD, platform_role="staff")
    client, csrf, _ = login(demo_app, "staff@ntx.test", PASSWORD)

    read = client.get(f"/api/dashboard/businesses/{business.id}/overview")
    assert read.status_code == 200

    write = client.patch(
        f"/api/dashboard/businesses/{business.id}/settings",
        json={"name": "Renamed By Staff"},
        headers=auth_headers(csrf),
    )
    assert write.status_code == 403
    assert "read-only" in write.get_json()["error"].lower()


def test_client_user_cannot_reach_any_admin_route(demo_app):
    business = make_business()
    user = make_platform_user(email="owner@client.test", password=PASSWORD, platform_role="none")
    make_membership(business.id, user.id, role="owner")

    client, csrf, _ = login(demo_app, "owner@client.test", PASSWORD)

    assert client.get("/api/admin/businesses").status_code == 403
    assert client.get("/api/admin/overview").status_code == 403
    assert client.get("/api/admin/conversations").status_code == 403
    assert client.get("/api/admin/delivery").status_code == 403
    assert client.get("/api/admin/webhooks").status_code == 403
    assert client.post(
        "/api/admin/businesses",
        json={"name": "Sneaky", "slug": "sneaky"},
        headers=auth_headers(csrf),
    ).status_code == 403


def test_viewer_role_cannot_write(demo_app):
    business = make_business()
    user = make_platform_user(email="viewer@client.test", password=PASSWORD, platform_role="none")
    make_membership(business.id, user.id, role="viewer")

    client, csrf, _ = login(demo_app, "viewer@client.test", PASSWORD)

    assert client.get(f"/api/dashboard/businesses/{business.id}/settings").status_code == 200
    write = client.patch(
        f"/api/dashboard/businesses/{business.id}/settings",
        json={"name": "Nope"},
        headers=auth_headers(csrf),
    )
    assert write.status_code == 403


def test_owner_role_can_write(demo_app):
    business = make_business()
    user = make_platform_user(email="owner@client.test", password=PASSWORD, platform_role="none")
    make_membership(business.id, user.id, role="owner")

    client, csrf, _ = login(demo_app, "owner@client.test", PASSWORD)
    response = client.patch(
        f"/api/dashboard/businesses/{business.id}/settings",
        json={"name": "Renamed By Owner"},
        headers=auth_headers(csrf),
    )
    assert response.status_code == 200
    assert response.get_json()["business"]["name"] == "Renamed By Owner"


def test_legacy_is_platform_admin_flag_still_grants_admin(demo_app):
    """Rows written before platform_role existed must not lose access."""
    from modules.db import session_scope
    from modules.models import PlatformUser
    from sqlalchemy import update

    user = make_platform_user(email="legacy@ntx.test", password=PASSWORD, platform_role="admin")
    db = session_scope()
    try:
        db.execute(
            update(PlatformUser)
            .where(PlatformUser.id == user.id)
            .values(platform_role="none", is_platform_admin=True)
        )
        db.commit()
    finally:
        db.close()

    client, _, _ = login(demo_app, "legacy@ntx.test", PASSWORD)
    assert client.get("/api/admin/businesses").status_code == 200
