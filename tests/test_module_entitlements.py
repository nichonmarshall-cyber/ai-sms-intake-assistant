"""Module entitlements gate the API, not just the navigation."""

from modules import entitlements
from modules.db import session_scope
from tests.conftest import (
    auth_headers,
    login,
    make_business,
    make_membership,
    make_platform_user,
)

PASSWORD = "correct-horse-battery-staple"


def _client_owner(business):
    user = make_platform_user(email="owner@client.test", password=PASSWORD, platform_role="none")
    make_membership(business.id, user.id, role="owner")
    return user


def test_new_business_gets_default_modules_only(demo_app):
    business = make_business()
    db = session_scope()
    try:
        enabled = entitlements.enabled_module_keys(db, business.id)
    finally:
        db.close()

    assert enabled == set(entitlements.DEFAULT_ENABLED_MODULES)
    # Phase 3 and 4 modules must not be silently switched on.
    assert "campaigns" not in enabled
    assert "local_seo" not in enabled


def test_navigation_omits_disabled_modules(demo_app):
    business = make_business()
    _client_owner(business)
    client, _, _ = login(demo_app, "owner@client.test", PASSWORD)

    payload = client.get(f"/api/dashboard/businesses/{business.id}/navigation").get_json()
    keys = {m["key"] for m in payload["modules"]}

    assert "overview" in keys
    assert "campaigns" not in keys


def test_disabled_module_api_returns_403_even_though_nav_hides_it(demo_app):
    """Hiding a link is not authorization."""
    business = make_business()
    _client_owner(business)

    db = session_scope()
    try:
        entitlements.set_module(db, business.id, "settings", False)
        db.commit()
    finally:
        db.close()

    client, _, _ = login(demo_app, "owner@client.test", PASSWORD)
    response = client.get(f"/api/dashboard/businesses/{business.id}/settings")
    assert response.status_code == 403


def test_admin_can_toggle_a_module(demo_app):
    business = make_business()
    make_platform_user(email="admin@ntx.test", password=PASSWORD, platform_role="admin")
    client, csrf, _ = login(demo_app, "admin@ntx.test", PASSWORD)

    response = client.put(
        f"/api/admin/businesses/{business.id}/modules/local_seo",
        json={"enabled": True},
        headers=auth_headers(csrf),
    )
    assert response.status_code == 200

    db = session_scope()
    try:
        assert "local_seo" in entitlements.enabled_module_keys(db, business.id)
    finally:
        db.close()


def test_toggling_an_unknown_module_is_rejected(demo_app):
    business = make_business()
    make_platform_user(email="admin@ntx.test", password=PASSWORD, platform_role="admin")
    client, csrf, _ = login(demo_app, "admin@ntx.test", PASSWORD)

    response = client.put(
        f"/api/admin/businesses/{business.id}/modules/not_a_real_module",
        json={"enabled": True},
        headers=auth_headers(csrf),
    )
    assert response.status_code == 404


def test_unimplemented_modules_are_flagged_not_faked(demo_app):
    """Phase 1a must never present mock Website/SEO/Analytics data."""
    implemented = {s.key for s in entitlements.MODULE_REGISTRY if s.implemented}
    assert implemented == {
        "overview",
        "leads",
        "conversations",
        "appointments",
        "ai_intake",
        "website",
        "analytics",
        "settings",
    }

    for key in ("local_seo", "reviews", "campaigns", "coupons"):
        assert entitlements.MODULES_BY_KEY[key].implemented is False
