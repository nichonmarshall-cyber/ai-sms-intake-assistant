"""Tenant-scoped Google Calendar integration.

The service-account credential is platform configuration. Business records only
store a calendar ID, timezone, and verification metadata—never a secret.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from modules.models import AppointmentRequest, Business, Lead

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"
CALENDAR_API = "https://www.googleapis.com/calendar/v3"


class CalendarConfigurationError(RuntimeError):
    pass


class CalendarProviderError(RuntimeError):
    pass


class CalendarConflictError(CalendarProviderError):
    pass


@dataclass(frozen=True)
class CalendarEventResult:
    event_id: str
    html_link: str | None


def _credential_source() -> str:
    return os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()


def credentials_configured() -> bool:
    return bool(_credential_source())


def _credentials() -> Credentials:
    source = _credential_source()
    if not source:
        raise CalendarConfigurationError("Google Calendar credentials are not configured.")
    try:
        if source.startswith("{"):
            credentials = Credentials.from_service_account_info(
                json.loads(source), scopes=[CALENDAR_SCOPE]
            )
        else:
            path = Path(source)
            credentials = Credentials.from_service_account_file(path, scopes=[CALENDAR_SCOPE])
        credentials.refresh(Request())
        return credentials
    except CalendarConfigurationError:
        raise
    except Exception as exc:
        raise CalendarConfigurationError("Google Calendar credentials could not be loaded.") from exc


def service_account_email() -> str | None:
    source = _credential_source()
    if not source:
        return None
    try:
        if source.startswith("{"):
            return str(json.loads(source).get("client_email") or "") or None
        return str(json.loads(Path(source).read_text(encoding="utf-8")).get("client_email") or "") or None
    except Exception:
        return None


def validate_timezone(value: str) -> str:
    cleaned = (value or "").strip() or "America/Chicago"
    try:
        ZoneInfo(cleaned)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Use a valid IANA timezone, such as America/Chicago.") from exc
    return cleaned


def parse_local_start(value: str, timezone_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat((value or "").strip())
    except ValueError as exc:
        raise ValueError("Choose a valid appointment date and time.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(validate_timezone(timezone_name)))
    return parsed.astimezone(timezone.utc)


def calendar_settings(business: Business) -> dict:
    raw = (business.settings or {}).get("calendar") or {}
    try:
        duration = min(480, max(15, int(raw.get("default_duration_minutes") or 60)))
    except (TypeError, ValueError):
        duration = 60
    return {
        "provider": "google",
        "calendar_id": str(raw.get("calendar_id") or ""),
        "calendar_name": str(raw.get("calendar_name") or ""),
        "timezone": str(raw.get("timezone") or "America/Chicago"),
        "verified_at": raw.get("verified_at"),
        "default_duration_minutes": duration,
    }


def connection_dto(business: Business) -> dict:
    settings = calendar_settings(business)
    return {
        **settings,
        "connected": bool(settings["calendar_id"] and settings["verified_at"]),
        "credentials_configured": credentials_configured(),
        "service_account_email": service_account_email(),
    }


def _request(method: str, path: str, *, payload: dict | None = None) -> dict:
    credentials = _credentials()
    try:
        response = httpx.request(
            method,
            f"{CALENDAR_API}{path}",
            headers={"Authorization": f"Bearer {credentials.token}"},
            json=payload,
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        raise CalendarProviderError("Google Calendar could not be reached.") from exc
    if response.status_code == 409:
        raise CalendarConflictError("That calendar event already exists.")
    if response.status_code >= 400:
        raise CalendarProviderError(
            "Google Calendar denied the request. Confirm that the calendar is shared with the NTX service account."
        )
    data = response.json()
    return data if isinstance(data, dict) else {}


def verify_calendar(calendar_id: str) -> dict:
    cleaned = (calendar_id or "").strip()
    if not cleaned:
        raise ValueError("Calendar ID is required.")
    return _request("GET", f"/calendars/{quote(cleaned, safe='')}")


def create_event(
    *,
    calendar_id: str,
    timezone_name: str,
    appointment: AppointmentRequest,
    business_name: str,
) -> CalendarEventResult:
    if appointment.scheduled_start_at is None:
        raise ValueError("The appointment start time is missing.")
    start = appointment.scheduled_start_at
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    end = start + timedelta(minutes=appointment.duration_minutes)
    event_id = (
        "appt"
        + hashlib.sha256(appointment.business_id.encode("utf-8")).hexdigest()[:12]
        + f"{appointment.id:08x}"
    )
    payload = {
        "id": event_id,
        "summary": f"{appointment.service_request or 'Service appointment'} — {appointment.customer_name or appointment.customer_phone}",
        "description": (
            f"Created by NTX Automation Co. for {business_name}.\n"
            f"Customer: {appointment.customer_name or 'Not provided'}\n"
            f"Phone: {appointment.customer_phone}\n"
            f"Requested service: {appointment.service_request or 'Not provided'}\n"
            f"Original preference: {appointment.requested_time_text or 'Not provided'}"
        ),
        "start": {"dateTime": start.isoformat(), "timeZone": timezone_name},
        "end": {"dateTime": end.isoformat(), "timeZone": timezone_name},
        "extendedProperties": {
            "private": {"ntxAppointmentRequestId": str(appointment.id)}
        },
    }
    calendar_path = f"/calendars/{quote(calendar_id, safe='')}/events"
    try:
        data = _request("POST", calendar_path, payload=payload)
    except CalendarConflictError:
        # The deterministic provider ID makes a retry safe if Google created
        # the event but our database commit failed afterward.
        data = _request("GET", f"{calendar_path}/{event_id}")
    provider_event_id = str(data.get("id") or "")
    if not provider_event_id:
        raise CalendarProviderError("Google Calendar did not return an event ID.")
    return CalendarEventResult(event_id=provider_event_id, html_link=data.get("htmlLink"))


def ensure_request_for_lead(db: DBSession, lead: Lead) -> AppointmentRequest | None:
    """Create one pending appointment request when intake captured a preference."""
    if not lead.business_id or not lead.requested_callback_time:
        return None
    existing = db.execute(
        select(AppointmentRequest).where(
            AppointmentRequest.business_id == lead.business_id,
            AppointmentRequest.lead_id == lead.id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    fields = lead.fields or {}
    customer_name = fields.get("name") or fields.get("customer_name")
    service_request = (
        fields.get("service_request")
        or fields.get("requested_service")
        or fields.get("service_type")
        or lead.business_summary
    )
    appointment = AppointmentRequest(
        business_id=lead.business_id,
        lead_id=lead.id,
        customer_name=str(customer_name)[:160] if customer_name else None,
        customer_phone=lead.phone,
        service_request=str(service_request)[:500] if service_request else None,
        requested_time_text=str(lead.requested_callback_time)[:160],
    )
    db.add(appointment)
    try:
        db.commit()
        db.refresh(appointment)
        return appointment
    except IntegrityError:
        db.rollback()
        return db.execute(
            select(AppointmentRequest).where(
                AppointmentRequest.business_id == lead.business_id,
                AppointmentRequest.lead_id == lead.id,
            )
        ).scalar_one_or_none()
