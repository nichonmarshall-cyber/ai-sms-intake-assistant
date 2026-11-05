"""Connect completed SMS intake to guarded Google Calendar automatic booking.

No model is allowed to create an event or decide if a slot is free. All
availability rules and provider writes are checked by application code.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from modules import calendar_service, entitlements, module_configuration
from modules.booking_time import parse_requested_time
from modules.models import AppointmentRequest, Business, Lead
from modules.tenancy import record_audit_event

logger = logging.getLogger(__name__)
OFFER_KEY = "__booking_offer"
OFFER_MINUTES = 30


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _configured(db, business_id: str, service_request: str | None):
    if not entitlements.is_module_enabled(db, business_id, "ai_scheduling"):
        return None
    config, _ = module_configuration.get_configuration(db, business_id, "ai_scheduling")
    duration = None
    booking_mode = config["booking_mode"]
    for service in config["services"]:
        if not service["enabled"]:
            continue
        if (service_request or "").strip().lower() in {service["label"].lower(), service["key"].replace("_", " ")}:
            booking_mode = service["booking_mode"]
            duration = service["duration_minutes"]
            config = {**config,
                      "buffer_before_minutes": service["buffer_before_minutes"],
                      "buffer_after_minutes": service["buffer_after_minutes"]}
            break
    if booking_mode != "automatic":
        return None
    return config, duration


def _save_offer(db, session, appointment_id: int, starts: list[datetime]) -> None:
    fields = dict(session.fields or {})
    fields[OFFER_KEY] = {
        "appointment_id": appointment_id,
        "starts": [slot.isoformat() for slot in starts],
        "expires": (datetime.now(timezone.utc) + timedelta(minutes=OFFER_MINUTES)).isoformat(),
    }
    session.fields = fields
    db.commit()


def _clear_offer(db, session) -> None:
    fields = dict(session.fields or {})
    fields.pop(OFFER_KEY, None)
    session.fields = fields
    db.commit()


def _format(start: datetime, zone: ZoneInfo) -> str:
    return start.astimezone(zone).strftime("%A, %B %d at %I:%M %p").replace(" at 0", " at ")


def _manual_reply(is_demo: bool) -> str:
    message = "We saved your request, but couldn't confirm calendar availability automatically. The team will review it."
    return message + (" This is a demo; no service has been arranged." if is_demo else "")


def _offer_options(db, session, appointment, desired, business, calendar, config, duration, is_demo):
    zone = ZoneInfo(calendar["timezone"])
    target = desired.astimezone(zone)
    # Same day first; pick close available alternatives rather than inventing times.
    slots = calendar_service.available_slots(
        calendar_id=calendar["calendar_id"], timezone_name=calendar["timezone"],
        configuration=config, start_date=target.date(), days=7,
        duration_minutes=duration,
    )
    slots = [slot for slot in slots if not _max_bookings_reached(
        db, appointment.business_id, slot, zone, config
    )]
    nearby = sorted(slots, key=lambda slot: (
        0 if slot.astimezone(zone).date() == target.date() else 1,
        abs((slot - desired).total_seconds()),
        slot,
    ))
    chosen = []
    for slot in nearby:
        if all(abs((slot - previous).total_seconds()) >= 60 * 60 for previous in chosen):
            chosen.append(slot)
        if len(chosen) == 3:
            break
    if not chosen:
        _save_offer(db, session, appointment.id, [])
        return "That time isn't available and there are no open slots in the following week. Please send another date and time, or the team can follow up." + (" Demo only; no service arranged." if is_demo else "")
    _save_offer(db, session, appointment.id, chosen)
    choices = "; ".join(f"{index}. {_format(slot, zone)}" for index, slot in enumerate(chosen, 1))
    return (
        f"{_format(desired, zone)} is outside the available booking schedule or already taken. "
        f"Available options: {choices}. Reply 1, 2 or 3, or send another exact date and time."
        + (" Demo: a selected slot creates a test calendar event, not a service booking." if is_demo else "")
    )


def _max_bookings_reached(db, business_id: str, start: datetime, zone: ZoneInfo, config: dict) -> bool:
    max_per_day = config.get("max_bookings_per_day")
    if max_per_day is None:
        return False
    local = start.astimezone(zone)
    day_start = datetime.combine(local.date(), datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)
    next_start = (datetime.combine(local.date(), datetime.min.time(), tzinfo=zone) + timedelta(days=1)).astimezone(timezone.utc)
    rows = db.execute(select(AppointmentRequest).where(
        AppointmentRequest.business_id == business_id,
        AppointmentRequest.status == "scheduled",
        AppointmentRequest.scheduled_start_at >= day_start,
        AppointmentRequest.scheduled_start_at < next_start,
    )).scalars()
    return sum(1 for _ in rows) >= max_per_day


def _book_or_offer(db, session, appointment, requested: datetime, runtime, config, duration: int) -> str:
    # Serialize automatic booking attempts for the same business in PostgreSQL.
    # This row lock is held through the final availability check and DB commit.
    business = db.execute(select(Business).where(
        Business.id == runtime.business_id,
    ).with_for_update()).scalar_one()
    appointment = db.execute(select(AppointmentRequest).where(
        AppointmentRequest.id == appointment.id,
        AppointmentRequest.business_id == runtime.business_id,
        AppointmentRequest.customer_phone == session.phone,
    ).with_for_update()).scalar_one()
    if appointment.status == "scheduled" and appointment.calendar_event_id:
        _clear_offer(db, session)
        return f"This request is already booked for {_format(_aware(appointment.scheduled_start_at), ZoneInfo(calendar_service.calendar_settings(business)['timezone']))}."
    if appointment.status not in {"pending", "sync_failed"}:
        return "This request is no longer open for scheduling. Please contact the business."

    calendar = calendar_service.calendar_settings(business)
    if not calendar["calendar_id"] or not calendar["verified_at"]:
        return "Your time preference was saved, but the business calendar isn't connected yet. The team will follow up."
    zone = ZoneInfo(calendar["timezone"])
    selected = _configured(db, runtime.business_id, appointment.service_request)
    if selected is None:
        return _manual_reply(runtime.is_demo)
    config, service_duration = selected
    duration = service_duration or duration

    # The slot generator enforces working hours, notice, advance window,
    # interval alignment, service duration, buffers, and Google busy periods.
    slots = calendar_service.available_slots(
        calendar_id=calendar["calendar_id"], timezone_name=calendar["timezone"],
        configuration=config, start_date=requested.astimezone(zone).date(),
        days=1, duration_minutes=duration,
    )
    is_open = requested in slots and not _max_bookings_reached(
        db, runtime.business_id, requested, zone, config,
    )
    if not is_open:
        return _offer_options(db, session, appointment, requested, business, calendar, config, duration, runtime.is_demo)

    # Recheck immediately before writing. Provider conflicts are not silently
    # treated as free, and no SMS says "booked" before Google returns an event.
    if not calendar_service.slot_is_free(
        calendar_id=calendar["calendar_id"], start=requested,
        duration_minutes=duration,
        buffer_before_minutes=config["buffer_before_minutes"],
        buffer_after_minutes=config["buffer_after_minutes"],
    ):
        return _offer_options(db, session, appointment, requested, business, calendar, config, duration, runtime.is_demo)

    appointment.scheduled_start_at = requested
    appointment.duration_minutes = duration
    try:
        event = calendar_service.create_event(
            calendar_id=calendar["calendar_id"], timezone_name=calendar["timezone"],
            appointment=appointment, business_name=business.name,
        )
    except calendar_service.CalendarProviderError:
        appointment.status = "pending"
        appointment.provider_error = "Automatic booking could not be completed in Google Calendar."
        db.commit()
        return _manual_reply(runtime.is_demo)
    appointment.status = "scheduled"
    appointment.calendar_event_id = event.event_id
    appointment.calendar_event_link = event.html_link
    appointment.provider_error = None
    if appointment.lead_id:
        lead = db.get(Lead, appointment.lead_id)
        if lead is not None and lead.business_id == runtime.business_id:
            lead.workflow_status = "scheduled"
    record_audit_event(
        db, action="appointment.automatic_schedule",
        business_id=runtime.business_id, target_type="appointment_request",
        target_id=str(appointment.id),
        details={"calendar_event_id": event.event_id, "source": "sms"},
    )
    _clear_offer(db, session)
    db.commit()
    date_text = _format(requested, zone)
    if runtime.is_demo:
        return f"Test booking added to the connected Google Calendar for {date_text}. This is an NTX demo; no actual service will be provided."
    return f"Confirmed! Your appointment with {business.name} is scheduled for {date_text}. Reply here if your plans change."


def complete_intake(db, session, lead: Lead, runtime) -> str | None:
    """Generate an SMS result for a completed lead, if automatic mode is on."""
    if not runtime.business_id:
        return None
    appointment = db.execute(select(AppointmentRequest).where(
        AppointmentRequest.business_id == runtime.business_id,
        AppointmentRequest.lead_id == lead.id,
    )).scalar_one_or_none()
    if appointment is None or _configured(db, runtime.business_id, appointment.service_request) is None:
        return None
    business = db.get(Business, runtime.business_id)
    calendar = calendar_service.calendar_settings(business)
    if not calendar["calendar_id"] or not calendar["verified_at"]:
        return _manual_reply(runtime.is_demo)
    requested = parse_requested_time(appointment.requested_time_text, calendar["timezone"])
    if requested is None:
        _save_offer(db, session, appointment.id, [])
        return "We've saved your request. For automatic booking, please reply with an exact date and time (for example, Friday at 4 PM). " + ("Demo only; no service booked." if runtime.is_demo else "")
    selected = _configured(db, runtime.business_id, appointment.service_request)
    config, service_duration = selected
    try:
        return _book_or_offer(db, session, appointment, requested, runtime, config,
                              service_duration or calendar["default_duration_minutes"])
    except (calendar_service.CalendarProviderError, calendar_service.CalendarConfigurationError):
        logger.exception("Automatic calendar availability failed for appointment %s", appointment.id)
        return _manual_reply(runtime.is_demo)


def handle_followup(db, session, body: str, runtime) -> str | None:
    """A completed intake may still await a booking slot choice."""
    offer = (session.fields or {}).get(OFFER_KEY)
    if not isinstance(offer, dict) or not runtime.business_id:
        return None
    try:
        expires = datetime.fromisoformat(offer["expires"])
        if _aware(expires) < datetime.now(timezone.utc):
            _clear_offer(db, session)
            return "That booking offer expired. Please contact the business or start a new request."
        appointment = db.execute(select(AppointmentRequest).where(
            AppointmentRequest.id == int(offer["appointment_id"]),
            AppointmentRequest.business_id == runtime.business_id,
            AppointmentRequest.customer_phone == session.phone,
        )).scalar_one_or_none()
        if appointment is None:
            _clear_offer(db, session)
            return "We couldn't find that booking request. Please start a new request."
        if appointment.status == "scheduled":
            _clear_offer(db, session)
            return "This appointment has already been scheduled."
        business = db.get(Business, runtime.business_id)
        calendar = calendar_service.calendar_settings(business)
        selected = _configured(db, runtime.business_id, appointment.service_request)
        if selected is None or not calendar["calendar_id"] or not calendar["verified_at"]:
            _clear_offer(db, session)
            return _manual_reply(runtime.is_demo)
        config, service_duration = selected
        options = offer.get("starts") or []
        answer = (body or "").strip()
        if answer in {"1", "2", "3"} and int(answer) <= len(options):
            requested = datetime.fromisoformat(options[int(answer) - 1])
        else:
            requested = parse_requested_time(answer, calendar["timezone"])
        if requested is None:
            return "Reply with one of the offered numbers or an exact date and time, such as Friday at 4 PM."
        if answer not in {"1", "2", "3"}:
            appointment.requested_time_text = answer[:160]
        return _book_or_offer(db, session, appointment, requested, runtime, config,
                              service_duration or calendar["default_duration_minutes"])
    except (ValueError, KeyError, TypeError):
        _clear_offer(db, session)
        return "That booking choice was invalid. Please contact the business or begin again."
    except (calendar_service.CalendarProviderError, calendar_service.CalendarConfigurationError):
        logger.exception("Automatic calendar follow-up failed for business %s", runtime.business_id)
        return _manual_reply(runtime.is_demo)
