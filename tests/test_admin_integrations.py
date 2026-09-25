"""Admin website-monitoring and Twilio-usage integrations."""

from types import SimpleNamespace

from modules import twilio_usage, website_monitoring
from modules.db import session_scope
from modules.models import Business
from tests.conftest import auth_headers, login, make_business, make_platform_user

PASSWORD = "correct-horse-battery-staple"


def _admin(demo_app):
    make_platform_user(email="integrations@ntx.test", password=PASSWORD, platform_role="admin")
    return login(demo_app, "integrations@ntx.test", PASSWORD)


def test_admin_can_attach_a_valid_website_to_business(demo_app):
    business = make_business()
    client, csrf, _ = _admin(demo_app)

    response = client.patch(
        f"/api/admin/businesses/{business.id}/website",
        json={"url": "https://Example.com/", "monitor_id": "12345"},
        headers=auth_headers(csrf),
    )

    assert response.status_code == 200
    assert response.get_json() == {"url": "https://example.com", "monitor_id": "12345"}
    db = session_scope()
    try:
        assert db.get(Business, business.id).settings["website"]["monitor_id"] == "12345"
    finally:
        db.close()


def test_website_configuration_rejects_non_http_urls(demo_app):
    business = make_business()
    client, csrf, _ = _admin(demo_app)
    response = client.patch(
        f"/api/admin/businesses/{business.id}/website",
        json={"url": "javascript:alert(1)", "monitor_id": "abc"},
        headers=auth_headers(csrf),
    )
    assert response.status_code == 400
    assert "url" in response.get_json()["fields"]


def test_website_monitoring_matches_business_by_monitor_id(demo_app, monkeypatch):
    business = make_business()
    db = session_scope()
    try:
        stored = db.get(Business, business.id)
        stored.settings = {"website": {"url": "https://example.com", "monitor_id": "42"}}
        db.commit()
    finally:
        db.close()
    client, _, _ = _admin(demo_app)
    monkeypatch.setenv("UPTIMEROBOT_API_KEY", "read-only-key")
    monkeypatch.setattr(website_monitoring, "list_monitors", lambda: [{
        "id": "42", "name": "Example", "url": "https://example.com", "status": "up",
        "uptime_7d": "100", "uptime_30d": "99.99", "uptime_90d": "99.9",
        "average_response_ms": 140,
    }])

    body = client.get("/api/admin/websites").get_json()
    row = next(item for item in body["sites"] if item["business"]["id"] == business.id)
    assert row["monitor"]["status"] == "up"
    assert body["metrics"]["online"] >= 1


def test_twilio_usage_uses_totalprice_without_summing_categories(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "secret")
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"usage_records": [
            {"category": "totalprice", "price": "5.41", "price_unit": "usd", "start_date": "2026-09-01", "end_date": "2026-09-25"},
            {"category": "sms", "price": "1.23", "price_unit": "usd", "count": "148", "count_unit": "messages", "usage": "148", "usage_unit": "messages"},
            {"category": "sms-messages-carrierfees", "price": "0.14", "price_unit": "usd", "count": "30", "count_unit": "segments", "usage": "30", "usage_unit": "segments"},
        ]},
    )
    monkeypatch.setattr(twilio_usage.httpx, "get", lambda *args, **kwargs: response)

    usage = twilio_usage.fetch_usage()
    assert usage["total_price"] == 5.41
    assert [row["key"] for row in usage["categories"]] == ["sms", "sms-messages-carrierfees"]


def test_twilio_usage_endpoint_is_admin_only(demo_app):
    business = make_business()
    user = make_platform_user(email="client-integrations@test.com", password=PASSWORD, platform_role="none")
    from tests.conftest import make_membership
    make_membership(business.id, user.id, role="owner")
    client, _, _ = login(demo_app, user.email, PASSWORD)
    assert client.get("/api/admin/twilio-usage").status_code == 403
