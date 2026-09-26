"""Client overview follows entitlements and uses isolated tenant data."""

from modules import entitlements, website_monitoring
from modules.db import session_scope
from modules.models import Business, Lead
from tests.conftest import login, make_business, make_membership, make_platform_user
from tests.test_client_conversations import _conversation

PASSWORD = "correct-horse-battery-staple"


def _lead(business_id: str, *, phone: str, name: str, source: str):
    db = session_scope()
    try:
        db.add(
            Lead(
                business_id=business_id,
                phone=phone,
                profile_key="auto_repair",
                fields={"name": name, "service_request": "Brake inspection", "source": source},
                status="completed",
                workflow_status="new",
                is_complete=True,
            )
        )
        db.commit()
    finally:
        db.close()


def test_overview_activity_and_sources_are_tenant_scoped(demo_app):
    business = make_business()
    other = make_business(name="Other", slug="other-overview")
    user = make_platform_user(
        email="owner@overview.test", password=PASSWORD, platform_role="none"
    )
    make_membership(business.id, user.id, role="owner")
    _lead(business.id, phone="+12145550101", name="Mine", source="google")
    _lead(other.id, phone="+19725550101", name="Theirs", source="facebook")
    _conversation(business.id, phone="+12145550102", name="My Conversation")
    _conversation(other.id, phone="+19725550102", name="Other Conversation")
    client, _, _ = login(demo_app, "owner@overview.test", PASSWORD)

    response = client.get(f"/api/dashboard/businesses/{business.id}/overview")

    assert response.status_code == 200
    body = response.get_json()
    assert body["metrics"]["total_leads"] == 1
    assert [item["customer_name"] for item in body["recent_leads"]] == ["Mine"]
    assert [item["customer_name"] for item in body["recent_conversations"]] == [
        "My Conversation"
    ]
    assert body["lead_sources"] == [{"source": "google", "count": 1}]
    assert sum(item["count"] for item in body["lead_activity"]) == 1
    assert len(body["lead_activity"]) == 7


def test_overview_matches_enabled_business_modules(demo_app, monkeypatch):
    business = make_business(name="Haley's Place", slug="haleys-place", with_defaults=False)
    db = session_scope()
    try:
        stored = db.get(Business, business.id)
        stored.settings = {
            "website": {
                "url": "https://haleysplacecreations.com",
                "monitor_id": "24",
            }
        }
        for key in ("overview", "website", "local_seo", "reviews", "analytics", "settings"):
            entitlements.set_module(db, business.id, key, True)
        db.commit()
    finally:
        db.close()

    user = make_platform_user(
        email="haley-overview@test.com", password=PASSWORD, platform_role="none"
    )
    make_membership(business.id, user.id, role="owner")
    monkeypatch.setenv("UPTIMEROBOT_API_KEY", "read-only-key")
    monkeypatch.setattr(website_monitoring, "list_monitors", lambda: [{
        "id": "24",
        "name": "Haley",
        "url": "https://haleysplacecreations.com",
        "status": "up",
        "uptime_7d": "100",
        "uptime_30d": "100",
        "uptime_90d": "100",
        "average_response_ms": 120,
    }])
    client, _, _ = login(demo_app, user.email, PASSWORD)

    response = client.get(f"/api/dashboard/businesses/{business.id}/overview")

    assert response.status_code == 200
    body = response.get_json()
    assert [item["key"] for item in body["enabled_modules"]] == [
        "overview",
        "website",
        "local_seo",
        "reviews",
        "analytics",
        "settings",
    ]
    assert body["website"]["monitor"]["id"] == "24"
    assert body["recent_leads"] == []
    assert body["recent_conversations"] == []
    assert body["appointment_requests"] == []
    assert "Gina" not in response.get_data(as_text=True)
