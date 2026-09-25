"""Tenant-scoped client website health."""

from modules import entitlements, website_monitoring
from modules.db import session_scope
from modules.models import Business
from tests.conftest import login, make_business, make_membership, make_platform_user

PASSWORD = "correct-horse-battery-staple"


def _website_business(name: str, slug: str, monitor_id: str, url: str):
    business = make_business(name=name, slug=slug)
    db = session_scope()
    try:
        stored = db.get(Business, business.id)
        stored.settings = {"website": {"url": url, "monitor_id": monitor_id}}
        entitlements.set_module(db, business.id, "website", True)
        db.commit()
    finally:
        db.close()
    return business


def test_client_website_automatically_uses_its_business_monitor(demo_app, monkeypatch):
    haley = _website_business("Haley's Place Creations", "haleys-place", "24", "https://haleysplacecreations.com")
    _website_business("Gina's Creations Dolls", "ginas-dolls", "19", "https://ginascreationdolls.com")
    user = make_platform_user(email="haley@test.com", password=PASSWORD, platform_role="none")
    make_membership(haley.id, user.id, role="owner")
    monkeypatch.setenv("UPTIMEROBOT_API_KEY", "read-only-key")
    monkeypatch.setattr(website_monitoring, "list_monitors", lambda: [
        {"id": "19", "name": "Gina", "url": "https://ginascreationdolls.com", "status": "up"},
        {"id": "24", "name": "Haley", "url": "https://haleysplacecreations.com", "status": "up", "uptime_7d": "100", "uptime_30d": "100", "uptime_90d": "100", "average_response_ms": 120},
    ])
    client, _, _ = login(demo_app, user.email, PASSWORD)

    response = client.get(f"/api/dashboard/businesses/{haley.id}/website")
    assert response.status_code == 200
    body = response.get_json()
    assert body["monitor"]["id"] == "24"
    assert body["website_url"] == "https://haleysplacecreations.com"
    assert "Gina" not in response.get_data(as_text=True)


def test_client_website_api_requires_entitlement(demo_app):
    business = make_business()
    user = make_platform_user(email="website-disabled@test.com", password=PASSWORD, platform_role="none")
    make_membership(business.id, user.id, role="owner")
    client, _, _ = login(demo_app, user.email, PASSWORD)
    assert client.get(f"/api/dashboard/businesses/{business.id}/website").status_code == 403
