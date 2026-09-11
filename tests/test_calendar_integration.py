from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import select

from modules import calendar_service
from modules.calendar_service import CalendarEventResult
from modules.conversation_store import record_lead
from modules.db import session_scope
from modules.models import AppointmentRequest, AuditEvent, Business, ConversationSession, Lead
from tests.conftest import auth_headers, login, make_business, make_membership, make_platform_user

PASSWORD = "correct-horse-battery-staple"


def _owner(business, *, email="calendar-owner@test.local", role="owner"):
    user = make_platform_user(email=email, password=PASSWORD, platform_role="none")
    make_membership(business.id, user.id, role=role)
    return user


def _appointment(business_id: str, *, phone="+12145550101") -> AppointmentRequest:
    db = session_scope()
    try:
        row = AppointmentRequest(
            business_id=business_id,
            customer_name="Jason Carter",
            customer_phone=phone,
            service_request="Brake inspection",
            requested_time_text="Friday morning",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


def test_completed_intake_creates_one_pending_appointment_request(demo_app):
    business = make_business()
    db = session_scope()
    try:
        session = ConversationSession(
            business_id=business.id,
            phone="+12145550111",
            state="completed",
            profile_key="auto_repair",
            history=[],
            fields={
                "customer_name": "Jordan Lee",
                "service_request": "Oil change",
                "preferred_service_time": "Tuesday afternoon",
            },
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(session)
        db.commit()
        record_lead(db, session, {"is_complete": True}, "completed")
        requests = list(db.execute(select(AppointmentRequest)).scalars())
    finally:
        db.close()

    assert len(requests) == 1
    assert requests[0].business_id == business.id
    assert requests[0].requested_time_text == "Tuesday afternoon"
    assert requests[0].status == "pending"


def test_appointment_list_is_tenant_scoped(demo_app):
    business = make_business()
    other = make_business(name="Other", slug="other-calendar")
    _owner(business)
    mine = _appointment(business.id)
    _appointment(other.id, phone="+19725550101")
    client, _, _ = login(demo_app, "calendar-owner@test.local", PASSWORD)

    response = client.get(f"/api/dashboard/businesses/{business.id}/appointments")

    assert response.status_code == 200
    assert [item["id"] for item in response.get_json()["items"]] == [mine.id]


def test_calendar_verify_stores_only_public_connection_metadata(demo_app):
    business = make_business()
    _owner(business)
    client, csrf, _ = login(demo_app, "calendar-owner@test.local", PASSWORD)

    with patch("modules.calendar_service.verify_calendar", return_value={"summary": "Miller Service"}):
        response = client.post(
            f"/api/dashboard/businesses/{business.id}/calendar/verify",
            json={
                "calendar_id": "miller@example.test",
                "timezone": "America/Chicago",
                "default_duration_minutes": 60,
            },
            headers=auth_headers(csrf),
        )

    assert response.status_code == 200
    assert response.get_json()["connection"]["connected"] is True
    db = session_scope()
    try:
        stored = db.get(Business, business.id).settings["calendar"]
    finally:
        db.close()
    assert stored["calendar_id"] == "miller@example.test"
    assert "credential" not in " ".join(stored.keys()).lower()


def test_owner_can_schedule_and_google_event_id_is_required(demo_app):
    business = make_business()
    user = _owner(business)
    appointment = _appointment(business.id)
    db = session_scope()
    try:
        stored = db.get(Business, business.id)
        stored.settings = {
            "calendar": {
                "calendar_id": "miller@example.test",
                "calendar_name": "Miller Service",
                "timezone": "America/Chicago",
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "default_duration_minutes": 60,
            }
        }
        db.commit()
    finally:
        db.close()
    client, csrf, _ = login(demo_app, "calendar-owner@test.local", PASSWORD)

    with patch(
        "modules.calendar_service.create_event",
        return_value=CalendarEventResult("google-event-1", "https://calendar.google.test/event"),
    ):
        response = client.patch(
            f"/api/dashboard/businesses/{business.id}/appointments/{appointment.id}",
            json={
                "action": "schedule",
                "scheduled_start": "2030-05-16T09:00",
                "duration_minutes": 60,
            },
            headers=auth_headers(csrf),
        )

    assert response.status_code == 200
    assert response.get_json()["appointment"]["status"] == "scheduled"
    assert response.get_json()["appointment"]["calendar_event_id"] == "google-event-1"
    db = session_scope()
    try:
        audit = db.execute(
            select(AuditEvent).where(AuditEvent.action == "appointment.schedule")
        ).scalar_one()
    finally:
        db.close()
    assert audit.actor_user_id == user.id


def test_google_event_payload_contains_tenant_context_without_credentials(demo_app):
    business = make_business()
    appointment = _appointment(business.id)
    appointment.scheduled_start_at = datetime(2030, 5, 16, 14, 0, tzinfo=timezone.utc)
    appointment.duration_minutes = 45

    with patch(
        "modules.calendar_service._request",
        return_value={"id": "provider-event", "htmlLink": "https://calendar.test/event"},
    ) as request_mock:
        result = calendar_service.create_event(
            calendar_id="miller calendar@example.test",
            timezone_name="America/Chicago",
            appointment=appointment,
            business_name=business.name,
        )

    assert result.event_id == "provider-event"
    path = request_mock.call_args.args[1]
    payload = request_mock.call_args.kwargs["payload"]
    assert "miller%20calendar%40example.test" in path
    assert payload["id"].startswith("appt")
    assert "Miller Auto Care" in payload["description"]
    assert "credential" not in str(payload).lower()


def test_provider_failure_remains_visible_and_does_not_mark_scheduled(demo_app):
    business = make_business()
    _owner(business)
    appointment = _appointment(business.id)
    db = session_scope()
    try:
        stored = db.get(Business, business.id)
        stored.settings = {
            "calendar": {
                "calendar_id": "miller@example.test",
                "calendar_name": "Miller Service",
                "timezone": "America/Chicago",
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "default_duration_minutes": 60,
            }
        }
        db.commit()
    finally:
        db.close()
    client, csrf, _ = login(demo_app, "calendar-owner@test.local", PASSWORD)

    with patch(
        "modules.calendar_service.create_event",
        side_effect=calendar_service.CalendarProviderError("Google Calendar could not be reached."),
    ):
        response = client.patch(
            f"/api/dashboard/businesses/{business.id}/appointments/{appointment.id}",
            json={"action": "schedule", "scheduled_start": "2030-05-16T09:00"},
            headers=auth_headers(csrf),
        )

    assert response.status_code == 502
    assert response.get_json()["appointment"]["status"] == "sync_failed"
    assert response.get_json()["appointment"]["calendar_event_id"] is None


def test_viewer_cannot_schedule_appointments(demo_app):
    business = make_business()
    _owner(business, email="calendar-viewer@test.local", role="viewer")
    appointment = _appointment(business.id)
    client, csrf, _ = login(demo_app, "calendar-viewer@test.local", PASSWORD)

    response = client.patch(
        f"/api/dashboard/businesses/{business.id}/appointments/{appointment.id}",
        json={"action": "decline"},
        headers=auth_headers(csrf),
    )

    assert response.status_code == 403


def test_platform_calendar_reports_each_tenant(demo_app):
    business = make_business()
    _appointment(business.id)
    admin = make_platform_user(password=PASSWORD, platform_role="admin")
    client, _, _ = login(demo_app, admin.email, PASSWORD)

    response = client.get("/api/admin/calendar")

    assert response.status_code == 200
    body = response.get_json()
    assert any(row["business"]["id"] == business.id for row in body["connections"])
    assert any(item["business"]["id"] == business.id for item in body["items"])
