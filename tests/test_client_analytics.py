"""Operational analytics uses real tenant-scoped platform records."""

from datetime import datetime, timedelta, timezone

from modules import entitlements
from modules.db import session_scope
from modules.models import AppointmentRequest, ConversationSession, Lead, MissedCallEvent
from tests.conftest import login, make_business, make_membership, make_platform_user


PASSWORD = "correct-horse-battery-staple"


def _seed(business_id: str, *, phone: str, source: str = "sms") -> None:
    now = datetime.now(timezone.utc)
    db = session_scope()
    try:
        lead = Lead(
            business_id=business_id,
            phone=phone,
            profile_key="roofing",
            fields={"name": "Test Lead", "source": source},
            status="completed",
            workflow_status="scheduled",
            is_complete=True,
            created_at=now,
        )
        db.add(lead)
        db.flush()
        db.add_all([
            ConversationSession(
                business_id=business_id,
                phone=phone,
                state="completed",
                history=[],
                fields={},
                expires_at=now + timedelta(minutes=45),
                created_at=now,
            ),
            AppointmentRequest(
                business_id=business_id,
                lead_id=lead.id,
                customer_phone=phone,
                status="scheduled",
                created_at=now,
            ),
            MissedCallEvent(
                business_id=business_id,
                call_sid=f"CA-{phone}",
                caller_phone=phone,
                twilio_number="+18173936339",
                source="missed_call",
                decision="sent",
                created_at=now,
            ),
        ])
        db.commit()
    finally:
        db.close()


def test_analytics_is_tenant_scoped_and_reports_real_metrics(demo_app):
    business = make_business()
    other = make_business(name="Other", slug="other-analytics")
    user = make_platform_user(email="analytics@client.test", password=PASSWORD, platform_role="none")
    make_membership(business.id, user.id, role="owner")
    _seed(business.id, phone="+12145550101", source="website")
    _seed(other.id, phone="+19725550101", source="referral")
    client, _, _ = login(demo_app, "analytics@client.test", PASSWORD)

    response = client.get(f"/api/dashboard/businesses/{business.id}/analytics?days=7")

    assert response.status_code == 200
    body = response.get_json()
    assert body["period"]["days"] == 7
    assert body["period"]["timezone"] == "America/Chicago"
    assert body["metrics"] == {
        "leads": 1,
        "completed_intakes": 1,
        "completion_rate": 100.0,
        "conversations": 1,
        "appointment_requests": 1,
        "scheduled_appointments": 1,
        "schedule_rate": 100.0,
        "missed_calls": 1,
        "followups_sent": 1,
    }
    assert body["lead_sources"] == [{"key": "website", "count": 1}]
    assert body["service_profiles"] == [{"key": "roofing", "count": 1}]
    assert body["workflow_statuses"] == [{"key": "scheduled", "count": 1}]
    assert len(body["activity"]) == 7
    assert sum(day["leads"] for day in body["activity"]) == 1


def test_analytics_defaults_invalid_range_to_thirty_days(demo_app):
    business = make_business()
    user = make_platform_user(email="range@client.test", password=PASSWORD, platform_role="none")
    make_membership(business.id, user.id, role="owner")
    client, _, _ = login(demo_app, "range@client.test", PASSWORD)

    body = client.get(f"/api/dashboard/businesses/{business.id}/analytics?days=365").get_json()

    assert body["period"]["days"] == 30
    assert len(body["activity"]) == 30


def test_analytics_api_respects_module_entitlement(demo_app):
    business = make_business()
    user = make_platform_user(email="disabled@client.test", password=PASSWORD, platform_role="none")
    make_membership(business.id, user.id, role="owner")
    db = session_scope()
    try:
        entitlements.set_module(db, business.id, "analytics", False)
        db.commit()
    finally:
        db.close()
    client, _, _ = login(demo_app, "disabled@client.test", PASSWORD)

    assert client.get(f"/api/dashboard/businesses/{business.id}/analytics").status_code == 403
