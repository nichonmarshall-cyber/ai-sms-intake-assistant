"""Public, read-only product demo workspace with fictional data only."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from modules import entitlements
from modules.auth import passwords
from modules.models import AppointmentRequest, Business, BusinessMembership, ConversationSession, Lead, MissedCallEvent, PlatformUser

DEMO_BUSINESS_ID = "ntx-product-demo"
DEMO_EMAIL = "demo@ntxautomation.invalid"
DEMO_SETTINGS = {
    "intake": {"enabled_profiles": ["auto_repair"], "default_profile_key": "auto_repair", "selection_mode": "single", "demo_disclaimer": True},
    "website": {"url": "https://example.com"},
    "calendar": {"provider": "google", "calendar_id": "demo-calendar", "calendar_name": "Northstar Demo Calendar", "timezone": "America/Chicago", "verified_at": "2026-01-01T00:00:00+00:00", "default_duration_minutes": 60},
    "business_hours": {"monday": "8:00 AM – 6:00 PM", "tuesday": "8:00 AM – 6:00 PM", "wednesday": "8:00 AM – 6:00 PM", "thursday": "8:00 AM – 6:00 PM", "friday": "8:00 AM – 6:00 PM"},
}


def ensure_demo_workspace(db) -> tuple[PlatformUser, Business]:
    """Create/update the one fictional viewer and its sample activity."""
    business = db.get(Business, DEMO_BUSINESS_ID)
    if business is None:
        business = Business(id=DEMO_BUSINESS_ID, name="Northstar Auto Care — Demo", slug="northstar-auto-care-demo", status="active", default_profile_key="auto_repair", settings=DEMO_SETTINGS)
        db.add(business)
        db.flush()
    else:
        business.name, business.settings = "Northstar Auto Care — Demo", DEMO_SETTINGS
    for key in (*entitlements.DEFAULT_ENABLED_MODULES, "website", "local_seo", "reviews"):
        entitlements.set_module(db, business.id, key, True)

    user = db.execute(select(PlatformUser).where(PlatformUser.email == DEMO_EMAIL)).scalar_one_or_none()
    if user is None:
        user = PlatformUser(id=str(uuid4()), email=DEMO_EMAIL, display_name="Product Demo", password_hash=passwords.hash_password(str(uuid4())), platform_role="none", is_platform_admin=False, is_active=True)
        db.add(user)
        db.flush()
    membership = db.execute(select(BusinessMembership).where(BusinessMembership.business_id == business.id, BusinessMembership.user_id == user.id)).scalar_one_or_none()
    if membership is None:
        db.add(BusinessMembership(business_id=business.id, user_id=user.id, role="viewer"))
    else:
        membership.role = "viewer"

    now = datetime.now(timezone.utc)
    leads = (("+12145550101", "Avery Collins", "Brake inspection", "new", 1), ("+12145550102", "Jordan Lee", "AC service", "qualified", 5), ("+12145550103", "Morgan Patel", "Check engine light", "scheduled", 28), ("+12145550104", "Riley Brooks", "Oil change", "closed", 53), ("+12145550105", "Casey Nguyen", "Tire rotation", "qualified", 76))
    for phone, name, service, status, hours_ago in leads:
        row = db.execute(select(Lead).where(Lead.business_id == business.id, Lead.phone == phone)).scalar_one_or_none()
        if row is None:
            received = now - timedelta(hours=hours_ago)
            db.add(Lead(business_id=business.id, phone=phone, profile_key="auto_repair", fields={"name": name, "service_request": service, "source": "Website form" if hours_ago % 2 else "Missed-call text", "demo": True}, status="completed", workflow_status=status, category="general_service", business_summary=f"{name} requested {service.lower()}.", termination_reason="completed", turn_count=5, is_complete=True, created_at=received, updated_at=received))
    db.flush()
    for phone, preference, status in (("+12145550101", "Tomorrow at 10:00 AM", "pending"), ("+12145550103", "Friday at 2:30 PM", "scheduled")):
        lead = db.execute(select(Lead).where(Lead.business_id == business.id, Lead.phone == phone)).scalar_one()
        existing = db.execute(select(AppointmentRequest).where(AppointmentRequest.business_id == business.id, AppointmentRequest.lead_id == lead.id)).scalar_one_or_none()
        if existing is None:
            db.add(AppointmentRequest(business_id=business.id, lead_id=lead.id, customer_name=lead.fields["name"], customer_phone=phone, service_request=lead.fields["service_request"], requested_time_text=preference, status=status, scheduled_start_at=(now + timedelta(days=2)) if status == "scheduled" else None, duration_minutes=60))
    sessions = (("+12145550101", "Avery Collins", "Brake inspection", "in_progress", 12), ("+12145550102", "Jordan Lee", "AC service", "completed", 48), ("+12145550103", "Morgan Patel", "Check engine light", "completed", 96))
    for phone, name, service, state, minutes_ago in sessions:
        row = db.execute(select(ConversationSession).where(ConversationSession.business_id == business.id, ConversationSession.phone == phone)).scalar_one_or_none()
        if row is None:
            updated = now - timedelta(minutes=minutes_ago)
            history = [{"role": "user", "content": f"Hi, I need help with {service.lower()}."}, {"role": "assistant", "content": "I can collect a few details for the shop. What is your name?"}, {"role": "user", "content": name}, {"role": "assistant", "content": "Thanks. What time works best for a callback?"}]
            db.add(ConversationSession(business_id=business.id, phone=phone, state=state, profile_key="auto_repair", history=history, fields={"name": name, "service_request": service}, turn_count=2, off_topic_strikes=0, terminated=False, opted_out=False, created_at=updated - timedelta(minutes=8), updated_at=updated, expires_at=now + timedelta(hours=12)))
    for index, hours_ago in enumerate((2, 31, 70), start=1):
        sid = f"CANTXDEMO{index:04d}"
        row = db.execute(select(MissedCallEvent).where(MissedCallEvent.call_sid == sid)).scalar_one_or_none()
        if row is None:
            db.add(MissedCallEvent(business_id=business.id, call_sid=sid, caller_phone=f"+121455502{index:02d}", twilio_number="+18175550199", source="missed_call", decision="message_sent", message_sid=f"SMNTXDEMO{index:04d}", delivery_status="delivered", created_at=now - timedelta(hours=hours_ago)))
    db.flush()
    return user, business
