"""AI Intake dashboard metrics and missed-call retention controls."""

from modules.db import session_scope
from modules.models import Lead, MissedCallEvent
from tests.conftest import (
    auth_headers,
    login,
    make_business,
    make_membership,
    make_platform_user,
)
from tests.test_client_conversations import _conversation

PASSWORD = "correct-horse-battery-staple"


def _member_business(*, role: str = "owner", email: str = "owner@miller.test"):
    business = make_business()
    user = make_platform_user(email=email, password=PASSWORD, platform_role="none")
    make_membership(business.id, user.id, role=role)
    return business


def _lead(business_id: str, *, complete: bool, status: str):
    db = session_scope()
    try:
        db.add(
            Lead(
                business_id=business_id,
                phone="+12145550999",
                profile_key="auto_repair",
                fields={"name": "Test Customer"},
                status=status,
                workflow_status="new",
                is_complete=complete,
            )
        )
        db.commit()
    finally:
        db.close()


def _missed_call(business_id: str, *, sid: str = "CAaiintake01") -> MissedCallEvent:
    db = session_scope()
    try:
        event = MissedCallEvent(
            business_id=business_id,
            call_sid=sid,
            caller_phone="+12145550111",
            twilio_number="+18175550142",
            source="missed_call",
            decision="message_sent",
            message_sid="SMaiintake01",
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        return event
    finally:
        db.close()


def test_ai_intake_reports_only_real_tenant_metrics(demo_app):
    business = _member_business()
    other = make_business(name="Other", slug="other")
    _conversation(business.id, phone="+12145550101", name="Active")
    _conversation(
        business.id, phone="+12145550102", name="Complete", state="completed"
    )
    _conversation(other.id, phone="+19725550101", name="Other")
    _lead(business.id, complete=True, status="completed")
    _lead(business.id, complete=False, status="escalated")
    _missed_call(business.id)
    _missed_call(other.id, sid="CAother01")
    client, _, _ = login(demo_app, "owner@miller.test", PASSWORD)

    response = client.get(f"/api/dashboard/businesses/{business.id}/ai-intake")

    assert response.status_code == 200
    body = response.get_json()
    assert body["metrics"] == {
        "active_sessions": 1,
        "completed_intakes": 1,
        "escalations": 1,
        "missed_calls": 1,
    }
    assert len(body["recent_sessions"]) == 2
    assert len(body["recent_missed_calls"]) == 1
    assert body["recent_missed_calls"][0]["caller_phone"] == "+12145550111"


def test_owner_can_archive_missed_call_and_action_is_tenant_scoped(demo_app):
    business = _member_business()
    other = make_business(name="Other", slug="other")
    event = _missed_call(business.id)
    other_event = _missed_call(other.id, sid="CAother01")
    client, csrf, _ = login(demo_app, "owner@miller.test", PASSWORD)

    blocked = client.patch(
        f"/api/dashboard/businesses/{business.id}/missed-calls/{other_event.id}",
        json={"archive": True},
        headers=auth_headers(csrf),
    )
    archived = client.patch(
        f"/api/dashboard/businesses/{business.id}/missed-calls/{event.id}",
        json={"archive": True},
        headers=auth_headers(csrf),
    )

    assert blocked.status_code == 404
    assert archived.status_code == 200
    assert archived.get_json()["event"]["archived_at"] is not None
    body = client.get(f"/api/dashboard/businesses/{business.id}/ai-intake").get_json()
    assert body["metrics"]["missed_calls"] == 0
    assert body["recent_missed_calls"] == []
    archived_body = client.get(
        f"/api/dashboard/businesses/{business.id}/ai-intake?include_archived=true"
    ).get_json()
    assert archived_body["metrics"]["missed_calls"] == 1
    assert archived_body["recent_missed_calls"][0]["archived_at"] is not None


def test_viewer_cannot_archive_missed_calls(demo_app):
    business = _member_business(role="viewer", email="viewer@miller.test")
    event = _missed_call(business.id)
    client, csrf, _ = login(demo_app, "viewer@miller.test", PASSWORD)

    response = client.patch(
        f"/api/dashboard/businesses/{business.id}/missed-calls/{event.id}",
        json={"archive": True},
        headers=auth_headers(csrf),
    )

    assert response.status_code == 403
