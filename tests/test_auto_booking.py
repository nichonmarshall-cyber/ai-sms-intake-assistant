"""Automatic SMS scheduling uses real provider availability and tenant settings."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import select

from modules import auto_booking, entitlements, module_configuration
from modules.calendar_service import CalendarEventResult
from modules.db import session_scope
from modules.models import (
    AppointmentRequest, Business, BusinessModuleConfiguration, ConversationSession,
)
from tests.conftest import make_business


def _setup():
    business = make_business(name="Miller Lawn Care", slug="auto-booking-lawn")
    db = session_scope()
    stored = db.get(Business, business.id)
    stored.settings = {
        "calendar": {
            "calendar_id": "miller@example.test",
            "calendar_name": "Miller Appointments",
            "timezone": "America/Chicago",
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "default_duration_minutes": 60,
        }
    }
    entitlements.set_module(db, business.id, "ai_scheduling", True)
    config = module_configuration.default_configuration("ai_scheduling")
    config["booking_mode"] = "automatic"
    db.add(BusinessModuleConfiguration(
        business_id=business.id, module_key="ai_scheduling", configuration=config,
        schema_version=1, version=1,
    ))
    session = ConversationSession(
        business_id=business.id, phone="+12145550101", state="completed",
        profile_key="lawn_care", terminated=True, history=[], fields={},
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=45),
    )
    db.add(session)
    db.flush()
    appointment = AppointmentRequest(
        business_id=business.id, customer_name="Nicholas",
        customer_phone="+12145550101", service_request="Lawn cut",
        requested_time_text="Friday at 7pm", status="pending",
    )
    db.add(appointment)
    db.commit()
    return db, session, appointment, SimpleNamespace(
        business_id=business.id, is_demo=True, business_name=business.name,
    )


def test_auto_booking_creates_google_event_only_for_open_slot(demo_app):
    db, session, appointment, runtime = _setup()
    try:
        start = datetime(2030, 5, 16, 14, tzinfo=timezone.utc)
        cfg, duration = auto_booking._configured(db, runtime.business_id, "Lawn cut")
        with (
            patch("modules.calendar_service.available_slots", return_value=[start]),
            patch("modules.calendar_service.slot_is_free", return_value=True),
            patch("modules.calendar_service.create_event",
                  return_value=CalendarEventResult("google-auto", "https://calendar.google.test/evt")) as create,
        ):
            reply = auto_booking._book_or_offer(db, session, appointment, start, runtime, cfg, duration or 60)
        assert "Test booking added" in reply
        assert create.call_count == 1
        db.refresh(appointment)
        assert appointment.status == "scheduled"
        assert appointment.calendar_event_id == "google-auto"
        assert auto_booking.OFFER_KEY not in session.fields
    finally:
        db.close()


def test_outside_hours_offers_alternatives_then_customer_selects(demo_app):
    db, session, appointment, runtime = _setup()
    try:
        requested = datetime(2030, 5, 17, 0, tzinfo=timezone.utc)
        alternative = datetime(2030, 5, 16, 21, tzinfo=timezone.utc)
        cfg, duration = auto_booking._configured(db, runtime.business_id, "Lawn cut")
        with (
            patch("modules.calendar_service.available_slots", side_effect=[[], [alternative]]),
            patch("modules.calendar_service.create_event") as create,
        ):
            reply = auto_booking._book_or_offer(db, session, appointment, requested, runtime, cfg, duration or 60)
            assert "Reply 1, 2 or 3" in reply
            create.assert_not_called()
        db.refresh(appointment)
        assert appointment.status == "pending"
        assert len(session.fields[auto_booking.OFFER_KEY]["starts"]) == 1
        with (
            patch("modules.calendar_service.available_slots", return_value=[alternative]),
            patch("modules.calendar_service.slot_is_free", return_value=True),
            patch("modules.calendar_service.create_event",
                  return_value=CalendarEventResult("google-alternative", None)),
        ):
            answer = auto_booking.handle_followup(db, session, "1", runtime)
        assert "Test booking added" in answer
        db.refresh(appointment)
        assert appointment.status == "scheduled"
    finally:
        db.close()


def test_failed_google_calendar_never_claims_booking(demo_app):
    db, session, appointment, runtime = _setup()
    try:
        start = datetime(2030, 5, 16, 14, tzinfo=timezone.utc)
        cfg, duration = auto_booking._configured(db, runtime.business_id, "Lawn cut")
        from modules.calendar_service import CalendarProviderError
        with (
            patch("modules.calendar_service.available_slots", return_value=[start]),
            patch("modules.calendar_service.slot_is_free", return_value=True),
            patch("modules.calendar_service.create_event",
                  side_effect=CalendarProviderError("provider unavailable")),
        ):
            reply = auto_booking._book_or_offer(db, session, appointment, start, runtime, cfg, duration or 60)
        assert "couldn't confirm" in reply
        db.refresh(appointment)
        assert appointment.status == "pending"
        assert appointment.calendar_event_id is None
    finally:
        db.close()
