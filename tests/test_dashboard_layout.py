"""Business-scoped dashboard layout settings."""

from modules import dashboard_layout
from modules.db import session_scope
from modules.models import Business
from tests.conftest import auth_headers, login, make_business, make_membership, make_platform_user


PASSWORD = "correct-horse-battery-staple"


def _business_owner():
    business = make_business()
    user = make_platform_user(email="layout-owner@test.com", password=PASSWORD, platform_role="none")
    make_membership(business.id, user.id, role="owner")
    return business, user


def test_layout_normalization_preserves_only_known_overview_widgets():
    layout = dashboard_layout.normalize_overview_layout(
        {
            "order": ["appointments", "not-real", "stats"],
            "visible": {"appointments": False, "not-real": True},
            "services_position": "top",
            "sizes": {"appointments": "wide", "stats": "not-real", "bogus": "wide"},
        },
        {"overview", "appointments", "settings"},
    )

    assert layout["order"] == ["appointments", "stats", "recent_leads", "recent_conversations"]
    assert layout["visible"]["appointments"] is False
    assert layout["visible"]["stats"] is True
    assert layout["services_position"] == "top"
    assert layout["sizes"] == {
        "stats": "wide",
        "recent_leads": "standard",
        "appointments": "wide",
        "recent_conversations": "wide",
    }
    assert layout["available_widgets"] == ["stats", "appointments", "services"]


def test_business_owner_saves_layout_and_overview_receives_it(demo_app):
    business, user = _business_owner()
    client, csrf, _ = login(demo_app, user.email, PASSWORD)

    response = client.patch(
        f"/api/dashboard/businesses/{business.id}/settings",
        json={
            "dashboard_layout": {
                "overview": {
                    "order": ["appointments", "stats", "recent_conversations", "recent_leads"],
                    "visible": {"stats": False, "services": False},
                    "services_position": "left",
                    "sizes": {"appointments": "wide", "recent_leads": "standard"},
                }
            }
        },
        headers=auth_headers(csrf),
    )

    assert response.status_code == 200
    saved = response.get_json()["dashboard_layout"]["overview"]
    assert saved["order"][0] == "appointments"
    assert saved["visible"]["stats"] is False
    assert saved["visible"]["services"] is False
    assert saved["services_position"] == "left"
    assert saved["sizes"]["appointments"] == "wide"
    assert saved["sizes"]["recent_leads"] == "standard"

    overview = client.get(f"/api/dashboard/businesses/{business.id}/overview")
    assert overview.status_code == 200
    assert overview.get_json()["dashboard_layout"]["overview"] == saved

    db = session_scope()
    try:
        stored = db.get(Business, business.id)
        assert stored.settings["dashboard_layout"]["overview"]["services_position"] == "left"
        assert stored.settings["dashboard_layout"]["overview"]["sizes"]["appointments"] == "wide"
    finally:
        db.close()


def test_layout_update_cannot_cross_tenant_boundaries(demo_app):
    _, user = _business_owner()
    other = make_business(name="Other Layout Co", slug="other-layout-co")
    client, csrf, _ = login(demo_app, user.email, PASSWORD)

    response = client.patch(
        f"/api/dashboard/businesses/{other.id}/settings",
        json={"dashboard_layout": {"overview": {"services_position": "left"}}},
        headers=auth_headers(csrf),
    )

    assert response.status_code == 403
