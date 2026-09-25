"""Control Center business management, analytics, and audit trail."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from modules.db import session_scope
from modules.models import (
    AppointmentRequest,
    AuditEvent,
    ConversationSession,
    Lead,
    MissedCallEvent,
)
from tests.conftest import (
    auth_headers,
    login,
    make_business,
    make_membership,
    make_platform_user,
)

PASSWORD = "correct-horse-battery-staple"


def _admin(demo_app):
    make_platform_user(email="admin@ntx.test", password=PASSWORD, platform_role="admin")
    return login(demo_app, "admin@ntx.test", PASSWORD)


def _audit_actions():
    db = session_scope()
    try:
        return list(db.execute(select(AuditEvent.action)).scalars())
    finally:
        db.close()


def test_create_business_seeds_default_modules_and_audits(demo_app):
    client, csrf, _ = _admin(demo_app)

    response = client.post(
        "/api/admin/businesses",
        json={"name": "Joy Boy Studio", "slug": "joy-boy-studio"},
        headers=auth_headers(csrf),
    )
    assert response.status_code == 201
    body = response.get_json()
    assert body["slug"] == "joy-boy-studio"
    assert "overview" in body["modules"]
    assert "business.create" in _audit_actions()


def test_invalid_slug_is_rejected_with_field_errors(demo_app):
    client, csrf, _ = _admin(demo_app)
    response = client.post(
        "/api/admin/businesses",
        json={"name": "Bad Slug", "slug": "Not A Slug"},
        headers=auth_headers(csrf),
    )
    assert response.status_code == 400
    assert "slug" in response.get_json()["fields"]


def test_duplicate_slug_is_rejected(demo_app):
    make_business(name="Existing", slug="existing-co")
    client, csrf, _ = _admin(demo_app)
    response = client.post(
        "/api/admin/businesses",
        json={"name": "Another", "slug": "existing-co"},
        headers=auth_headers(csrf),
    )
    assert response.status_code == 409


def test_business_list_supports_search_and_pagination(demo_app):
    make_business(name="Miller Auto Care", slug="miller-auto")
    make_business(name="North Texas Roofing", slug="ntx-roofing")
    client, _, _ = _admin(demo_app)

    all_items = client.get("/api/admin/businesses").get_json()
    assert all_items["total"] >= 2
    assert all_items["page_size"] == 25

    filtered = client.get("/api/admin/businesses?q=roofing").get_json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["slug"] == "ntx-roofing"


def test_business_detail_includes_modules_and_counts(demo_app):
    business = make_business()
    client, _, _ = _admin(demo_app)

    body = client.get(f"/api/admin/businesses/{business.id}").get_json()
    assert body["business"]["id"] == business.id
    assert len(body["modules"]) == 14
    assert body["counts"]["leads"] == 0


def test_update_business_status_is_audited(demo_app):
    business = make_business()
    client, csrf, _ = _admin(demo_app)

    response = client.patch(
        f"/api/admin/businesses/{business.id}",
        json={"status": "suspended"},
        headers=auth_headers(csrf),
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "suspended"
    assert "business.update" in _audit_actions()


def test_assign_phone_number_is_audited(demo_app):
    business = make_business()
    client, csrf, _ = _admin(demo_app)

    response = client.post(
        f"/api/admin/businesses/{business.id}/phone-numbers",
        json={"phone": "+18175550142", "label": "Front desk"},
        headers=auth_headers(csrf),
    )
    assert response.status_code == 201
    assert response.get_json()["phone"] == "+18175550142"
    assert "business.phone_number.assign" in _audit_actions()


def test_duplicate_phone_number_is_rejected_cleanly(demo_app):
    first = make_business(name="First", slug="first-phone")
    second = make_business(name="Second", slug="second-phone")
    client, csrf, _ = _admin(demo_app)
    headers = auth_headers(csrf)

    assert client.post(
        f"/api/admin/businesses/{first.id}/phone-numbers",
        json={"phone": "+1 (817) 555-0142"},
        headers=headers,
    ).status_code == 201
    response = client.post(
        f"/api/admin/businesses/{second.id}/phone-numbers",
        json={"phone": "+18175550142"},
        headers=headers,
    )

    assert response.status_code == 409
    assert "phone" in response.get_json()["fields"]


def test_admin_can_disable_and_relabel_phone_number(demo_app):
    business = make_business()
    client, csrf, _ = _admin(demo_app)
    headers = auth_headers(csrf)
    number = client.post(
        f"/api/admin/businesses/{business.id}/phone-numbers",
        json={"phone": "+18175550143", "label": "Main"},
        headers=headers,
    ).get_json()

    response = client.patch(
        f"/api/admin/businesses/{business.id}/phone-numbers/{number['id']}",
        json={"enabled": False, "label": "Overflow"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.get_json()["enabled"] is False
    assert response.get_json()["label"] == "Overflow"
    assert "business.phone_number.update" in _audit_actions()


def test_admin_can_update_and_remove_membership(demo_app):
    business = make_business()
    user = make_platform_user(email="member@client.test", password=PASSWORD)
    membership = make_membership(business.id, user.id, role="viewer")
    client, csrf, _ = _admin(demo_app)
    headers = auth_headers(csrf)

    updated = client.post(
        f"/api/admin/businesses/{business.id}/memberships",
        json={"user_id": user.id, "role": "manager"},
        headers=headers,
    )
    assert updated.status_code == 201
    assert updated.get_json()["role"] == "manager"

    removed = client.delete(
        f"/api/admin/businesses/{business.id}/memberships/{membership.id}",
        headers=headers,
    )
    assert removed.status_code == 204
    actions = _audit_actions()
    assert "membership.upsert" in actions
    assert "membership.remove" in actions


def test_created_user_response_omits_credentials(demo_app):
    client, csrf, _ = _admin(demo_app)
    response = client.post(
        "/api/admin/users",
        json={
            "email": "new.owner@client.test",
            "password": "another-long-passphrase",
            "platform_role": "none",
        },
        headers=auth_headers(csrf),
    )
    assert response.status_code == 201
    body = response.get_data(as_text=True)
    assert "password" not in body
    assert "hash" not in body


def test_weak_password_is_rejected(demo_app):
    client, csrf, _ = _admin(demo_app)
    response = client.post(
        "/api/admin/users",
        json={"email": "weak@client.test", "password": "short", "platform_role": "none"},
        headers=auth_headers(csrf),
    )
    assert response.status_code == 400
    assert "password" in response.get_json()["fields"]


def test_admin_can_revoke_another_users_sessions(demo_app):
    victim = make_platform_user(email="victim@client.test", password=PASSWORD, platform_role="none")
    victim_client, _, _ = login(demo_app, "victim@client.test", PASSWORD)
    assert victim_client.get("/api/auth/me").status_code == 200

    admin_client, csrf, _ = _admin(demo_app)
    response = admin_client.post(
        f"/api/admin/users/{victim.id}/revoke-sessions", headers=auth_headers(csrf)
    )
    assert response.status_code == 200
    assert response.get_json()["revoked"] == 1
    assert victim_client.get("/api/auth/me").status_code == 401


def test_platform_overview_declares_what_it_cannot_measure(demo_app):
    client, _, _ = _admin(demo_app)
    body = client.get("/api/admin/overview").get_json()

    assert body["active_businesses"] >= 0
    unavailable = {item["key"] for item in body["unavailable"]}
    assert "websites_online" in unavailable
    assert "active_alerts" in unavailable


def test_platform_analytics_compares_businesses_and_totals_real_records(demo_app):
    first = make_business(name="First Client", slug="first-client")
    second = make_business(name="Second Client", slug="second-client")
    now = datetime.now(timezone.utc)
    db = session_scope()
    try:
        lead = Lead(
            business_id=first.id,
            phone="+18175550101",
            profile_key="roofing",
            fields={"source": "Direct SMS"},
            status="completed",
            workflow_status="scheduled",
            is_complete=True,
            created_at=now,
        )
        db.add(lead)
        db.flush()
        db.add_all([
            ConversationSession(
                business_id=first.id,
                phone="+18175550101",
                state="completed",
                history=[],
                fields={},
                expires_at=now + timedelta(minutes=45),
                created_at=now,
            ),
            AppointmentRequest(
                business_id=first.id,
                lead_id=lead.id,
                customer_phone="+18175550101",
                status="scheduled",
                created_at=now,
            ),
            MissedCallEvent(
                business_id=first.id,
                call_sid="CA-admin-analytics-sent",
                caller_phone="+18175550101",
                twilio_number="+18173936339",
                decision="sent",
                created_at=now,
            ),
            MissedCallEvent(
                business_id=second.id,
                call_sid="CA-admin-analytics-disabled",
                caller_phone="+18175550102",
                twilio_number="+18173936339",
                decision="feature_disabled",
                created_at=now,
            ),
        ])
        db.commit()
    finally:
        db.close()

    client, _, _ = _admin(demo_app)
    response = client.get("/api/admin/analytics?days=7")

    assert response.status_code == 200
    body = response.get_json()
    assert body["period"]["days"] == 7
    assert body["metrics"]["leads"] == 1
    assert body["metrics"]["completed_intakes"] == 1
    assert body["metrics"]["scheduled_appointments"] == 1
    assert body["metrics"]["missed_calls"] == 2
    assert body["metrics"]["followups_sent"] == 1
    rows = {row["id"]: row for row in body["businesses"]}
    assert rows[first.id]["completion_rate"] == 100.0
    assert rows[first.id]["followups_sent"] == 1
    assert rows[second.id]["missed_calls"] == 1
    assert rows[second.id]["followups_sent"] == 0


def test_client_cannot_access_platform_analytics(demo_app):
    business = make_business(name="Client Only", slug="client-only")
    user = make_platform_user(
        email="client-only@client.test", password=PASSWORD, platform_role="none"
    )
    make_membership(business.id, user.id, role="owner")
    client, _, _ = login(demo_app, "client-only@client.test", PASSWORD)

    assert client.get("/api/admin/analytics").status_code == 403
