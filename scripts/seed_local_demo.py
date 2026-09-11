"""Seed a safe local client account and sample dashboard activity.

This helper refuses to touch PostgreSQL or a production Flask environment.
Run it from the repository root so the package imports resolve consistently:

    py -m scripts.seed_local_demo --email client@ntx.local
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from modules import entitlements
from modules.auth import passwords
from modules.db import get_database_url, init_db, is_sqlite, session_scope
from modules.models import (
    AppointmentRequest,
    Business,
    BusinessMembership,
    ConversationSession,
    Lead,
    MissedCallEvent,
    PlatformUser,
)
from modules.tenancy import ensure_legacy_business, record_audit_event


LOCAL_CLIENT_BUSINESS_ID = "local-miller-auto"
LOCAL_CLIENT_SETTINGS = {
    "intake": {
        "enabled_profiles": ["auto_repair"],
        "default_profile_key": "auto_repair",
        "selection_mode": "single",
        "demo_disclaimer": True,
    },
    "missed_calls": {"enabled": False},
}


SAMPLE_LEADS = (
    {
        "phone": "+12145550101",
        "profile_key": "auto_repair",
        "name": "Jason Carter",
        "service": "Brake inspection",
        "workflow_status": "new",
        "hours_ago": 1,
    },
    {
        "phone": "+12145550102",
        "profile_key": "auto_repair",
        "name": "Sarah Mitchell",
        "service": "AC not blowing cold",
        "workflow_status": "qualified",
        "hours_ago": 3,
    },
    {
        "phone": "+12145550103",
        "profile_key": "auto_repair",
        "name": "Michael Rodriguez",
        "service": "Check engine light",
        "workflow_status": "needs_review",
        "hours_ago": 7,
    },
    {
        "phone": "+12145550104",
        "profile_key": "roofing",
        "name": "Amanda Lee",
        "service": "Roof leak inspection",
        "workflow_status": "scheduled",
        "hours_ago": 25,
    },
    {
        "phone": "+12145550105",
        "profile_key": "lawn_care",
        "name": "David Thompson",
        "service": "Weekly lawn service",
        "workflow_status": "qualified",
        "hours_ago": 48,
    },
)

SAMPLE_CONVERSATIONS = (
    {
        "phone": "+12145550101",
        "name": "Jason Carter",
        "service_request": "Brake inspection",
        "state": "in_progress",
        "profile_key": "auto_repair",
        "minutes_ago": 8,
        "history": [
            {"role": "user", "content": "Hi, my brakes started squeaking this morning."},
            {
                "role": "assistant",
                "content": "I can help collect a few details for the shop. What is your name?",
            },
            {"role": "user", "content": "Jason Carter."},
            {
                "role": "assistant",
                "content": "Thanks, Jason. What year, make, and model is the vehicle?",
            },
            {"role": "user", "content": "2018 Honda Accord."},
            {
                "role": "assistant",
                "content": "Got it. Is there a preferred time for the team to call you back?",
            },
        ],
        "fields": {
            "name": "Jason Carter",
            "service_request": "Brake inspection",
            "vehicle_year": "2018",
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
        },
    },
    {
        "phone": "+12145550102",
        "name": "Sarah Mitchell",
        "service_request": "AC not blowing cold",
        "state": "completed",
        "profile_key": "auto_repair",
        "minutes_ago": 42,
        "history": [
            {"role": "user", "content": "My AC blows warm when I am sitting still."},
            {
                "role": "assistant",
                "content": "I can pass that along. What is your name and vehicle?",
            },
            {"role": "user", "content": "Sarah Mitchell, 2020 Toyota RAV4."},
            {
                "role": "assistant",
                "content": "What time is best for the shop to follow up?",
            },
            {"role": "user", "content": "Tomorrow after 1 PM."},
            {
                "role": "assistant",
                "content": "Thanks, Sarah. The team will follow up to confirm availability and pricing.",
            },
        ],
        "fields": {
            "name": "Sarah Mitchell",
            "service_request": "AC not blowing cold",
            "vehicle_year": "2020",
            "vehicle_make": "Toyota",
            "vehicle_model": "RAV4",
            "preferred_callback_time": "Tomorrow after 1 PM",
        },
    },
    {
        "phone": "+12145550103",
        "name": "Michael Rodriguez",
        "service_request": "Check engine light",
        "state": "completed",
        "profile_key": "auto_repair",
        "minutes_ago": 95,
        "history": [
            {"role": "user", "content": "My check engine light came on. Can I still drive it?"},
            {
                "role": "assistant",
                "content": "If the light is flashing or the vehicle is running poorly, stop driving and seek immediate help. Is the light solid or flashing?",
            },
            {"role": "user", "content": "Solid. The car feels normal."},
            {
                "role": "assistant",
                "content": "Thanks. I can collect your details so the shop can advise you. What is your name?",
            },
            {"role": "user", "content": "Michael Rodriguez."},
            {
                "role": "assistant",
                "content": "The team will follow up. If the light begins flashing or the car changes behavior, stop driving it.",
            },
        ],
        "fields": {
            "name": "Michael Rodriguez",
            "service_request": "Check engine light",
        },
    },
)


def _guard_local_sqlite() -> None:
    database_url = get_database_url()
    flask_env = os.getenv("FLASK_ENV", "development").strip().lower()
    if flask_env == "production" or not is_sqlite(database_url):
        raise RuntimeError(
            "Local demo seeding is allowed only with FLASK_ENV=development and a SQLite DATABASE_URL."
        )


def _read_password() -> str:
    password = getpass.getpass("Client password: ")
    confirm = getpass.getpass("Confirm client password: ")
    if password != confirm:
        raise ValueError("Passwords do not match.")
    error = passwords.validate_password_strength(password)
    if error:
        raise ValueError(error)
    return password


def _upsert_client(db, *, email: str, name: str, password: str) -> PlatformUser:
    user = db.execute(select(PlatformUser).where(PlatformUser.email == email)).scalar_one_or_none()
    if user is not None and user.platform_role in {"admin", "staff"}:
        raise ValueError("Use a separate email; this account already has platform access.")
    if user is None:
        user = PlatformUser(
            id=str(uuid4()),
            email=email,
            display_name=name,
            password_hash=passwords.hash_password(password),
            platform_role="none",
            is_platform_admin=False,
            is_active=True,
        )
        db.add(user)
        db.flush()
    else:
        user.display_name = name
        user.password_hash = passwords.hash_password(password)
        user.platform_role = "none"
        user.is_platform_admin = False
        user.is_active = True
    return user


def _ensure_client_business(db) -> Business:
    business = db.get(Business, LOCAL_CLIENT_BUSINESS_ID)
    if business is None:
        business = Business(
            id=LOCAL_CLIENT_BUSINESS_ID,
            name="Miller Auto Care",
            slug="miller-auto-care-local",
            status="active",
            default_profile_key="auto_repair",
            settings=LOCAL_CLIENT_SETTINGS,
        )
        db.add(business)
        db.flush()
    entitlements.apply_defaults(db, business.id)
    return business


def _ensure_membership(db, *, business_id: str, user_id: str) -> None:
    membership = db.execute(
        select(BusinessMembership).where(
            BusinessMembership.business_id == business_id,
            BusinessMembership.user_id == user_id,
        )
    ).scalar_one_or_none()
    if membership is None:
        db.add(
            BusinessMembership(
                business_id=business_id,
                user_id=user_id,
                role="owner",
            )
        )
    else:
        membership.role = "owner"


def _seed_activity(db, *, business_id: str) -> tuple[int, int, int, int]:
    now = datetime.now(timezone.utc)
    lead_count = 0
    for item in SAMPLE_LEADS:
        existing = db.execute(
            select(Lead).where(
                Lead.business_id == business_id,
                Lead.phone == item["phone"],
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        received = now - timedelta(hours=item["hours_ago"])
        db.add(
            Lead(
                business_id=business_id,
                phone=item["phone"],
                profile_key=item["profile_key"],
                fields={
                    "name": item["name"],
                    "service_request": item["service"],
                    "source": "demo_seed",
                },
                status="completed",
                workflow_status=item["workflow_status"],
                category="general_service",
                business_summary=f"{item['name']} requested {item['service'].lower()}.",
                termination_reason="completed",
                turn_count=5,
                off_topic_strikes=0,
                is_complete=True,
                created_at=received,
                updated_at=received,
            )
        )
        lead_count += 1

    db.flush()
    appointment_count = 0
    sample_preferences = {
        "+12145550101": "Friday morning",
        "+12145550102": "Tomorrow after 1 PM",
    }
    for phone, preference in sample_preferences.items():
        lead = db.execute(
            select(Lead).where(Lead.business_id == business_id, Lead.phone == phone)
        ).scalar_one_or_none()
        if lead is None:
            continue
        existing = db.execute(
            select(AppointmentRequest).where(
                AppointmentRequest.business_id == business_id,
                AppointmentRequest.lead_id == lead.id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        db.add(
            AppointmentRequest(
                business_id=business_id,
                lead_id=lead.id,
                customer_name=(lead.fields or {}).get("name"),
                customer_phone=lead.phone,
                service_request=(lead.fields or {}).get("service_request"),
                requested_time_text=preference,
                status="pending",
            )
        )
        appointment_count += 1

    call_count = 0
    for index, hours_ago in enumerate((2, 28), start=1):
        call_sid = f"CAlocaldashboarddemo{index:02d}"
        existing = db.execute(
            select(MissedCallEvent).where(MissedCallEvent.call_sid == call_sid)
        ).scalar_one_or_none()
        if existing is not None:
            continue
        db.add(
            MissedCallEvent(
                business_id=business_id,
                call_sid=call_sid,
                caller_phone=f"+1214555020{index}",
                twilio_number="+18173936339",
                source="missed_call",
                decision="message_sent",
                message_sid=f"SMlocaldashboarddemo{index:02d}",
                created_at=now - timedelta(hours=hours_ago),
            )
        )
        call_count += 1
    conversation_count = 0
    for item in SAMPLE_CONVERSATIONS:
        existing = db.execute(
            select(ConversationSession).where(
                ConversationSession.business_id == business_id,
                ConversationSession.phone == item["phone"],
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        updated_at = now - timedelta(minutes=item["minutes_ago"])
        db.add(
            ConversationSession(
                business_id=business_id,
                phone=item["phone"],
                state=item["state"],
                profile_key=item["profile_key"],
                history=item["history"],
                fields=item["fields"],
                turn_count=sum(1 for message in item["history"] if message["role"] == "assistant"),
                off_topic_strikes=0,
                terminated=False,
                opted_out=False,
                requested_callback_time=item["fields"].get("preferred_callback_time"),
                created_at=updated_at - timedelta(minutes=12),
                updated_at=updated_at,
                expires_at=now + timedelta(hours=12),
            )
        )
        conversation_count += 1
    return lead_count, call_count, conversation_count, appointment_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the local NTX dashboard demo.")
    parser.add_argument("--email", required=True, help="Email for the client-facing test account.")
    parser.add_argument("--name", default="Miller Auto Care Owner")
    args = parser.parse_args()

    try:
        _guard_local_sqlite()
        password = _read_password()
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    init_db()
    db = session_scope()
    try:
        ensure_legacy_business(db)
        business = _ensure_client_business(db)
        user = _upsert_client(
            db,
            email=args.email.strip().lower(),
            name=args.name.strip() or "Demo Client",
            password=password,
        )
        _ensure_membership(db, business_id=business.id, user_id=user.id)
        leads_added, calls_added, conversations_added, appointments_added = _seed_activity(
            db, business_id=business.id
        )
        record_audit_event(
            db,
            action="local.demo.seed",
            target_type="business",
            target_id=business.id,
            business_id=business.id,
            actor_user_id=user.id,
            details={
                "leads_added": leads_added,
                "missed_calls_added": calls_added,
                "conversations_added": conversations_added,
                "appointments_added": appointments_added,
            },
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        db.close()

    print(f"Local demo ready for {args.email.strip().lower()}.")
    print(f"Seeded {leads_added} new leads and {calls_added} new missed calls.")
    print(f"Seeded {conversations_added} stored conversation timelines.")
    print(f"Seeded {appointments_added} appointment requests.")
    print(f"Open /login; the client account will route to /b/{LOCAL_CLIENT_BUSINESS_ID}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
