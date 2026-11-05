"""Explicit SMS recovery must remain tenant-scoped and idempotent."""

from datetime import datetime, timezone
from unittest.mock import patch

from modules import entitlements
from modules.db import session_scope
from modules.models import AppointmentRequest, Business, BusinessPhoneNumber
from tests.conftest import auth_headers, login, make_business, make_membership, make_platform_user

PASSWORD = "correct-horse-battery-staple"


def test_retry_requires_business_number_and_never_sends_twice(demo_app):
    business = make_business()
    owner = make_platform_user(
        email="retry-owner@test.local", password=PASSWORD, platform_role="none",
    )
    make_membership(business.id, owner.id, role="owner")
    db = session_scope()
    try:
        stored = db.get(Business, business.id)
        stored.settings = {"calendar": {
            "calendar_id": "appointments@example.test",
            "timezone": "America/Chicago",
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "default_duration_minutes": 60,
        }}
        row = AppointmentRequest(
            business_id=business.id, customer_name="Customer",
            customer_phone="+12145550101", service_request="Lawn care",
            requested_time_text="Tuesday afternoon", status="scheduled",
            scheduled_start_at=datetime(2030, 5, 14, 14, 0, tzinfo=timezone.utc),
            calendar_event_id="calendar-event-existing",
        )
        db.add(row)
        entitlements.set_module(db, business.id, "ai_scheduling", True)
        db.commit()
        appointment_id = row.id
    finally:
        db.close()

    client, csrf, _ = login(demo_app, owner.email, PASSWORD)
    endpoint = f"/api/dashboard/businesses/{business.id}/appointments/{appointment_id}"
    with patch("modules.outbound_sms.send") as send:
        missing = client.patch(endpoint, json={"action": "retry_sms"}, headers=auth_headers(csrf))
        assert missing.status_code == 409
        send.assert_not_called()

    db = session_scope()
    try:
        db.add(BusinessPhoneNumber(
            business_id=business.id, phone="+18175550100",
            label="Business SMS", enabled=True, settings={},
        ))
        db.commit()
    finally:
        db.close()
    with patch("modules.outbound_sms.send", return_value="SMretryOnce") as send:
        success = client.patch(endpoint, json={"action": "retry_sms"}, headers=auth_headers(csrf))
        assert success.status_code == 200
        assert success.get_json()["appointment"]["approval_notification"]["sent"] is True
        assert send.call_args.kwargs["from_phone"] == "+18175550100"

        duplicate = client.patch(endpoint, json={"action": "retry_sms"}, headers=auth_headers(csrf))
        assert duplicate.status_code == 409
        assert send.call_count == 1


def test_retry_cannot_send_for_other_business(demo_app):
    first = make_business()
    second = make_business(name="Separate", slug="retry-other-tenant")
    owner = make_platform_user(
        email="retry-isolation@test.local", password=PASSWORD, platform_role="none",
    )
    make_membership(first.id, owner.id, role="owner")
    db = session_scope()
    try:
        row = AppointmentRequest(
            business_id=second.id, customer_phone="+12145550101",
            status="scheduled", calendar_event_id="other-event",
            scheduled_start_at=datetime(2030, 5, 14, 14, 0, tzinfo=timezone.utc),
        )
        db.add(row)
        db.commit()
        appointment_id = row.id
    finally:
        db.close()
    client, csrf, _ = login(demo_app, owner.email, PASSWORD)
    response = client.patch(
        f"/api/dashboard/businesses/{second.id}/appointments/{appointment_id}",
        json={"action": "retry_sms"}, headers=auth_headers(csrf),
    )
    assert response.status_code == 403
