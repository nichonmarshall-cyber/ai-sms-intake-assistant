"""Google reporting is entitled and mapped to the requested tenant."""

from modules import entitlements, google_visibility
from modules.db import session_scope
from modules.models import Business
from tests.conftest import auth_headers, login, make_business, make_membership, make_platform_user

PASSWORD = "correct-horse-battery-staple"


def test_google_settings_are_validated_and_scoped(demo_app, monkeypatch):
    first = make_business()
    second = make_business(name="Second", slug="second-google")
    admin = make_platform_user(email="google-admin@test.com", password=PASSWORD)
    admin_client, csrf, _ = login(demo_app, admin.email, PASSWORD)
    path = f"/api/admin/businesses/{first.id}/google-visibility"
    assert admin_client.patch(path, json={"search_property": "bad", "profile_location": "../other"}, headers=auth_headers(csrf)).status_code == 400
    response = admin_client.patch(path, json={"search_property": "sc-domain:first.test", "profile_location": "accounts/12/locations/34", "profile_url": "https://maps.google.com/?cid=1"}, headers=auth_headers(csrf))
    assert response.status_code == 200

    db = session_scope()
    try:
        assert db.get(Business, second.id).settings.get("google_visibility") is None
        entitlements.set_module(db, first.id, "local_seo", True)
        entitlements.set_module(db, first.id, "reviews", True)
        entitlements.set_module(db, second.id, "local_seo", True)
        db.commit()
    finally:
        db.close()

    owner = make_platform_user(email="google-owner@test.com", password=PASSWORD, platform_role="none")
    make_membership(first.id, owner.id)
    client, _, _ = login(demo_app, owner.email, PASSWORD)
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "configured")
    seen = []
    def fake_search(property_url):
        seen.append(property_url)
        return {"clicks": 5}
    monkeypatch.setattr(google_visibility, "search_console", fake_search)
    own = client.get(f"/api/dashboard/businesses/{first.id}/local-seo")
    assert own.get_json()["data"]["clicks"] == 5
    assert seen == ["sc-domain:first.test"]
    assert client.get(f"/api/dashboard/businesses/{second.id}/local-seo").status_code == 403
    assert client.get(f"/api/dashboard/businesses/{second.id}/reviews").status_code == 403


def test_unconnected_google_pages_show_no_fake_metrics(demo_app):
    business = make_business()
    db = session_scope()
    try:
        entitlements.set_module(db, business.id, "local_seo", True)
        entitlements.set_module(db, business.id, "reviews", True)
        db.commit()
    finally:
        db.close()
    owner = make_platform_user(email="empty-google@test.com", password=PASSWORD, platform_role="none")
    make_membership(business.id, owner.id)
    client, _, _ = login(demo_app, owner.email, PASSWORD)
    for endpoint in ("local-seo", "reviews"):
        body = client.get(f"/api/dashboard/businesses/{business.id}/{endpoint}").get_json()
        assert body["status"] == "not_connected"
        assert body["data"] is None
