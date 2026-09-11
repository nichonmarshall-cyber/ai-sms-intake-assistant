"""Client Dashboard API. Scoped to one business the caller is a member of."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, jsonify, request
from sqlalchemy import Integer, String, cast, func, or_, select

from modules import calendar_service, entitlements
from modules.auth.decorators import require_business_access, require_module
from modules.models import AppointmentRequest, Business, ConversationSession, Lead, MissedCallEvent
from modules.serializers import (
    appointment_dto,
    business_dto,
    conversation_detail_dto,
    conversation_summary_dto,
    lead_dto,
    missed_call_dto,
)
from modules.tenancy import record_audit_event

client_bp = Blueprint("client", __name__, url_prefix="/api/dashboard")

LEAD_WORKFLOW_STATUSES = {"new", "qualified", "needs_review", "scheduled", "closed"}
CONVERSATION_STATES = {"awaiting_profile_selection", "in_progress", "completed", "terminated"}
APPOINTMENT_STATUSES = {"pending", "scheduled", "declined", "cancelled", "sync_failed"}
MAX_PAGE_SIZE = 100


def _page_args() -> tuple[int, int]:
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    try:
        size = min(MAX_PAGE_SIZE, max(1, int(request.args.get("page_size", 25))))
    except ValueError:
        size = 25
    return page, size


@client_bp.get("/businesses/<business_id>/navigation")
@require_business_access()
def navigation(business_id: str):
    business = g.db.get(Business, business_id)
    if business is None:
        return jsonify({"error": "Business not found."}), 404
    return jsonify(
        {
            "business": {"id": business.id, "name": business.name, "slug": business.slug},
            "modules": entitlements.navigation_for(g.db, business_id),
            "role": g.business_role,
        }
    ), 200


@client_bp.get("/businesses/<business_id>/overview")
@require_business_access()
@require_module("overview")
def overview(business_id: str):
    """Counts come from real rows. Everything not yet built is declared, not faked."""
    lead_count = g.db.execute(
        select(func.count()).select_from(Lead).where(Lead.business_id == business_id)
    ).scalar_one()
    open_leads = g.db.execute(
        select(func.count())
        .select_from(Lead)
        .where(Lead.business_id == business_id, Lead.workflow_status == "new")
    ).scalar_one()
    missed_calls = g.db.execute(
        select(func.count())
        .select_from(MissedCallEvent)
        .where(MissedCallEvent.business_id == business_id)
    ).scalar_one()
    open_conversations = g.db.execute(
        select(func.count())
        .select_from(ConversationSession)
        .where(
            ConversationSession.business_id == business_id,
            ConversationSession.state.in_({"awaiting_profile_selection", "in_progress"}),
        )
    ).scalar_one()
    pending_appointments = g.db.execute(
        select(func.count())
        .select_from(AppointmentRequest)
        .where(
            AppointmentRequest.business_id == business_id,
            AppointmentRequest.status.in_({"pending", "sync_failed"}),
        )
    ).scalar_one()
    recent_leads = list(
        g.db.execute(
            select(Lead)
            .where(Lead.business_id == business_id, Lead.archived_at.is_(None))
            .order_by(Lead.created_at.desc(), Lead.id.desc())
            .limit(6)
        ).scalars()
    )
    recent_sessions = list(
        g.db.execute(
            select(ConversationSession)
            .where(ConversationSession.business_id == business_id)
            .order_by(ConversationSession.updated_at.desc(), ConversationSession.id.desc())
            .limit(4)
        ).scalars()
    )
    all_leads = list(
        g.db.execute(select(Lead).where(Lead.business_id == business_id)).scalars()
    )
    source_counts = Counter(
        str((lead.fields or {}).get("source") or "Direct SMS").strip() or "Direct SMS"
        for lead in all_leads
    )
    today = datetime.now(timezone.utc).date()
    daily_counts = Counter(
        lead.created_at.date()
        for lead in all_leads
        if lead.created_at and lead.created_at.date() >= today - timedelta(days=6)
    )
    appointment_requests = list(
        g.db.execute(
            select(AppointmentRequest)
            .where(
                AppointmentRequest.business_id == business_id,
                AppointmentRequest.status.in_({"pending", "sync_failed"}),
            )
            .order_by(AppointmentRequest.created_at.desc(), AppointmentRequest.id.desc())
            .limit(2)
        ).scalars()
    )
    business = g.db.get(Business, business_id)

    return jsonify(
        {
            "metrics": {
                "total_leads": lead_count,
                "new_leads": open_leads,
                "open_conversations": open_conversations,
                "missed_calls_handled": missed_calls,
                "pending_approval": pending_appointments,
            },
            "recent_leads": [lead_dto(lead) for lead in recent_leads],
            "recent_conversations": [conversation_summary_dto(row) for row in recent_sessions],
            "appointment_requests": [appointment_dto(row) for row in appointment_requests],
            "calendar": calendar_service.connection_dto(business),
            "lead_sources": [
                {"source": source, "count": count}
                for source, count in sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))
            ],
            "lead_activity": [
                {
                    "date": (today - timedelta(days=offset)).isoformat(),
                    "count": daily_counts[today - timedelta(days=offset)],
                }
                for offset in range(6, -1, -1)
            ],
            "unavailable": [
                {
                    "key": "response_rate",
                    "reason": "Requires provider delivery timestamps; message history alone cannot calculate it.",
                },
            ],
        }
    ), 200


@client_bp.get("/businesses/<business_id>/appointments")
@require_business_access()
@require_module("appointments")
def list_appointments(business_id: str):
    status = (request.args.get("status") or "").strip().lower()
    if status and status not in APPOINTMENT_STATUSES:
        return jsonify({"error": "Invalid appointment status."}), 400
    query = select(AppointmentRequest).where(AppointmentRequest.business_id == business_id)
    if status:
        query = query.where(AppointmentRequest.status == status)
    rows = list(
        g.db.execute(
            query.order_by(
                AppointmentRequest.scheduled_start_at.asc().nullslast(),
                AppointmentRequest.created_at.desc(),
            ).limit(100)
        ).scalars()
    )
    business = g.db.get(Business, business_id)
    return jsonify(
        {
            "items": [appointment_dto(row) for row in rows],
            "connection": calendar_service.connection_dto(business),
            "statuses": sorted(APPOINTMENT_STATUSES),
        }
    ), 200


@client_bp.patch("/businesses/<business_id>/appointments/<int:appointment_id>")
@require_business_access(write=True)
@require_module("appointments")
def update_appointment(business_id: str, appointment_id: int):
    appointment = g.db.execute(
        select(AppointmentRequest).where(
            AppointmentRequest.id == appointment_id,
            AppointmentRequest.business_id == business_id,
        )
    ).scalar_one_or_none()
    if appointment is None:
        return jsonify({"error": "Appointment request not found."}), 404
    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action") or "").strip().lower()

    if action == "decline":
        if appointment.status == "scheduled":
            return jsonify({"error": "A scheduled calendar event cannot be declined here."}), 409
        appointment.status = "declined"
        appointment.provider_error = None
        record_audit_event(
            g.db,
            action="appointment.decline",
            target_type="appointment_request",
            target_id=str(appointment.id),
            business_id=business_id,
            actor_user_id=g.current_user.id,
        )
        g.db.commit()
        return jsonify({"appointment": appointment_dto(appointment)}), 200

    if action != "schedule":
        return jsonify({"error": "Use action schedule or decline."}), 400
    if appointment.status == "scheduled" and appointment.calendar_event_id:
        return jsonify({"appointment": appointment_dto(appointment)}), 200

    business = g.db.get(Business, business_id)
    connection = calendar_service.calendar_settings(business)
    if not connection["calendar_id"] or not connection["verified_at"]:
        return jsonify({"error": "Connect and verify Google Calendar before scheduling."}), 409
    try:
        duration = int(payload.get("duration_minutes") or connection["default_duration_minutes"])
    except (TypeError, ValueError):
        return jsonify({"error": "Duration must be a number of minutes."}), 400
    if duration < 15 or duration > 480:
        return jsonify({"error": "Duration must be between 15 and 480 minutes."}), 400
    try:
        start = calendar_service.parse_local_start(
            str(payload.get("scheduled_start") or ""), connection["timezone"]
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if start < datetime.now(timezone.utc) - timedelta(minutes=5):
        return jsonify({"error": "Choose a future appointment time."}), 400

    appointment.scheduled_start_at = start
    appointment.duration_minutes = duration
    appointment.scheduled_by_user_id = g.current_user.id
    appointment.provider_error = None
    try:
        result = calendar_service.create_event(
            calendar_id=connection["calendar_id"],
            timezone_name=connection["timezone"],
            appointment=appointment,
            business_name=business.name,
        )
    except (calendar_service.CalendarConfigurationError, calendar_service.CalendarProviderError) as exc:
        appointment.status = "sync_failed"
        appointment.provider_error = str(exc)[:255]
        g.db.commit()
        return jsonify({"error": str(exc), "appointment": appointment_dto(appointment)}), 502

    appointment.status = "scheduled"
    appointment.calendar_event_id = result.event_id
    appointment.calendar_event_link = result.html_link
    if appointment.lead_id:
        lead = g.db.get(Lead, appointment.lead_id)
        if lead is not None and lead.business_id == business_id:
            lead.workflow_status = "scheduled"
    record_audit_event(
        g.db,
        action="appointment.schedule",
        target_type="appointment_request",
        target_id=str(appointment.id),
        business_id=business_id,
        actor_user_id=g.current_user.id,
        details={"calendar_event_id": result.event_id, "duration_minutes": duration},
    )
    g.db.commit()
    return jsonify({"appointment": appointment_dto(appointment)}), 200


@client_bp.post("/businesses/<business_id>/calendar/verify")
@require_business_access(write=True)
@require_module("appointments")
def verify_calendar_connection(business_id: str):
    business = g.db.get(Business, business_id)
    if business is None:
        return jsonify({"error": "Business not found."}), 404
    payload = request.get_json(silent=True) or {}
    calendar_id = str(payload.get("calendar_id") or "").strip()
    if len(calendar_id) > 320:
        return jsonify({"error": "Calendar ID must be 320 characters or fewer."}), 400
    try:
        timezone_name = calendar_service.validate_timezone(str(payload.get("timezone") or ""))
        duration = int(payload.get("default_duration_minutes") or 60)
        if duration < 15 or duration > 480:
            raise ValueError("Default duration must be between 15 and 480 minutes.")
        provider_calendar = calendar_service.verify_calendar(calendar_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except (calendar_service.CalendarConfigurationError, calendar_service.CalendarProviderError) as exc:
        return jsonify({"error": str(exc)}), 502

    settings = dict(business.settings or {})
    settings["calendar"] = {
        "provider": "google",
        "calendar_id": calendar_id,
        "calendar_name": str(provider_calendar.get("summary") or calendar_id)[:160],
        "timezone": timezone_name,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "default_duration_minutes": duration,
    }
    business.settings = settings
    record_audit_event(
        g.db,
        action="calendar.verify",
        target_type="business",
        target_id=business_id,
        business_id=business_id,
        actor_user_id=g.current_user.id,
        details={"calendar_name": settings["calendar"]["calendar_name"]},
    )
    g.db.commit()
    return jsonify({"connection": calendar_service.connection_dto(business)}), 200


@client_bp.post("/businesses/<business_id>/calendar/disconnect")
@require_business_access(write=True)
@require_module("appointments")
def disconnect_calendar(business_id: str):
    business = g.db.get(Business, business_id)
    if business is None:
        return jsonify({"error": "Business not found."}), 404
    settings = dict(business.settings or {})
    calendar = dict(settings.get("calendar") or {})
    calendar.update({"calendar_id": "", "calendar_name": "", "verified_at": None})
    settings["calendar"] = calendar
    business.settings = settings
    record_audit_event(
        g.db,
        action="calendar.disconnect",
        target_type="business",
        target_id=business_id,
        business_id=business_id,
        actor_user_id=g.current_user.id,
    )
    g.db.commit()
    return jsonify({"connection": calendar_service.connection_dto(business)}), 200


@client_bp.get("/businesses/<business_id>/leads")
@require_business_access()
@require_module("leads")
def list_leads(business_id: str):
    page, size = _page_args()
    search = (request.args.get("q") or "").strip().lower()
    workflow_status = (request.args.get("status") or "").strip().lower()
    include_archived = (request.args.get("include_archived") or "").strip().lower() == "true"

    if workflow_status and workflow_status not in LEAD_WORKFLOW_STATUSES:
        return jsonify({"error": "Invalid lead status."}), 400

    query = select(Lead).where(Lead.business_id == business_id)
    if not include_archived:
        query = query.where(Lead.archived_at.is_(None))
    if workflow_status:
        query = query.where(Lead.workflow_status == workflow_status)
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                func.lower(Lead.phone).like(pattern),
                func.lower(func.coalesce(Lead.business_summary, "")).like(pattern),
                func.lower(cast(Lead.fields, String)).like(pattern),
            )
        )

    total = g.db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = list(
        g.db.execute(
            query.order_by(Lead.created_at.desc(), Lead.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        ).scalars()
    )
    return jsonify(
        {
            "items": [lead_dto(lead) for lead in rows],
            "total": total,
            "page": page,
            "page_size": size,
            "statuses": sorted(LEAD_WORKFLOW_STATUSES),
        }
    ), 200


@client_bp.patch("/businesses/<business_id>/leads/<int:lead_id>")
@require_business_access(write=True)
@require_module("leads")
def update_lead(business_id: str, lead_id: int):
    lead = g.db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.business_id == business_id)
    ).scalar_one_or_none()
    if lead is None:
        return jsonify({"error": "Lead not found."}), 404

    payload = request.get_json(silent=True) or {}
    changed = {}

    if "workflow_status" in payload:
        workflow_status = (payload.get("workflow_status") or "").strip().lower()
        if workflow_status not in LEAD_WORKFLOW_STATUSES:
            return jsonify(
                {"error": "Validation failed.", "fields": {"workflow_status": "Invalid status."}}
            ), 400
        lead.workflow_status = workflow_status
        changed["workflow_status"] = workflow_status

    if "client_notes" in payload:
        notes = payload.get("client_notes")
        if notes is not None and not isinstance(notes, str):
            return jsonify(
                {"error": "Validation failed.", "fields": {"client_notes": "Must be text."}}
            ), 400
        notes = (notes or "").strip()
        if len(notes) > 4000:
            return jsonify(
                {"error": "Validation failed.", "fields": {"client_notes": "Maximum 4000 characters."}}
            ), 400
        lead.client_notes = notes or None
        changed["client_notes"] = "updated"

    if "archive" in payload:
        archive = payload.get("archive")
        if not isinstance(archive, bool):
            return jsonify(
                {"error": "Validation failed.", "fields": {"archive": "Must be true or false."}}
            ), 400
        if archive and lead.archived_at is None:
            from datetime import datetime, timezone

            lead.archived_at = datetime.now(timezone.utc)
            lead.archived_by_user_id = g.current_user.id
            changed["archived"] = True
        elif not archive and lead.archived_at is not None:
            lead.archived_at = None
            lead.archived_by_user_id = None
            changed["archived"] = False

    if not changed:
        return jsonify({"error": "No supported changes supplied."}), 400

    record_audit_event(
        g.db,
        action="lead.update",
        target_type="lead",
        target_id=str(lead.id),
        business_id=business_id,
        actor_user_id=g.current_user.id,
        details=changed,
    )
    g.db.commit()
    return jsonify({"lead": lead_dto(lead)}), 200


@client_bp.get("/businesses/<business_id>/conversations")
@require_business_access()
@require_module("conversations")
def list_conversations(business_id: str):
    page, size = _page_args()
    search = (request.args.get("q") or "").strip().lower()
    state = (request.args.get("state") or "").strip().lower()

    if state and state not in CONVERSATION_STATES:
        return jsonify({"error": "Invalid conversation state."}), 400

    query = select(ConversationSession).where(ConversationSession.business_id == business_id)
    if state:
        query = query.where(ConversationSession.state == state)
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                func.lower(ConversationSession.phone).like(pattern),
                func.lower(cast(ConversationSession.fields, String)).like(pattern),
            )
        )

    total = g.db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = list(
        g.db.execute(
            query.order_by(ConversationSession.updated_at.desc(), ConversationSession.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        ).scalars()
    )
    return jsonify(
        {
            "items": [conversation_summary_dto(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": size,
            "states": sorted(CONVERSATION_STATES),
        }
    ), 200


@client_bp.get("/businesses/<business_id>/conversations/<int:conversation_id>")
@require_business_access()
@require_module("conversations")
def get_conversation(business_id: str, conversation_id: int):
    row = g.db.execute(
        select(ConversationSession).where(
            ConversationSession.id == conversation_id,
            ConversationSession.business_id == business_id,
        )
    ).scalar_one_or_none()
    if row is None:
        return jsonify({"error": "Conversation not found."}), 404
    return jsonify({"conversation": conversation_detail_dto(row)}), 200


@client_bp.get("/businesses/<business_id>/ai-intake")
@require_business_access()
@require_module("ai_intake")
def ai_intake(business_id: str):
    active_states = ("awaiting_profile_selection", "in_progress")
    include_archived = (request.args.get("include_archived") or "").strip().lower() == "true"
    active_sessions = g.db.execute(
        select(func.count())
        .select_from(ConversationSession)
        .where(
            ConversationSession.business_id == business_id,
            ConversationSession.state.in_(active_states),
        )
    ).scalar_one()
    completed_intakes = g.db.execute(
        select(func.count())
        .select_from(Lead)
        .where(Lead.business_id == business_id, Lead.is_complete.is_(True))
    ).scalar_one()
    escalations = g.db.execute(
        select(func.count())
        .select_from(Lead)
        .where(Lead.business_id == business_id, Lead.status == "escalated")
    ).scalar_one()
    missed_query = select(MissedCallEvent).where(MissedCallEvent.business_id == business_id)
    if not include_archived:
        missed_query = missed_query.where(MissedCallEvent.archived_at.is_(None))
    missed_calls = g.db.execute(
        select(func.count()).select_from(missed_query.subquery())
    ).scalar_one()
    behavior = g.db.execute(
        select(
            func.coalesce(func.avg(ConversationSession.turn_count), 0),
            func.coalesce(func.sum(ConversationSession.off_topic_strikes), 0),
            func.coalesce(func.sum(cast(ConversationSession.opted_out, Integer)), 0),
        ).where(ConversationSession.business_id == business_id)
    ).one()
    recent_calls = list(
        g.db.execute(
            missed_query
            .order_by(MissedCallEvent.created_at.desc(), MissedCallEvent.id.desc())
            .limit(25)
        ).scalars()
    )
    recent_sessions = list(
        g.db.execute(
            select(ConversationSession)
            .where(ConversationSession.business_id == business_id)
            .order_by(ConversationSession.updated_at.desc(), ConversationSession.id.desc())
            .limit(5)
        ).scalars()
    )

    return jsonify(
        {
            "metrics": {
                "active_sessions": active_sessions,
                "completed_intakes": completed_intakes,
                "escalations": escalations,
                "missed_calls": missed_calls,
            },
            "behavior": {
                "average_turns": round(float(behavior[0] or 0), 1),
                "off_topic_strikes": int(behavior[1] or 0),
                "opted_out_sessions": int(behavior[2] or 0),
            },
            "recent_missed_calls": [missed_call_dto(event) for event in recent_calls],
            "recent_sessions": [conversation_summary_dto(row) for row in recent_sessions],
            "unavailable": [
                {
                    "key": "fallback_rate",
                    "reason": "Fallback outcomes are not stored as structured events yet.",
                }
            ],
        }
    ), 200


@client_bp.patch("/businesses/<business_id>/missed-calls/<int:event_id>")
@require_business_access(write=True)
@require_module("ai_intake")
def update_missed_call(business_id: str, event_id: int):
    event = g.db.execute(
        select(MissedCallEvent).where(
            MissedCallEvent.id == event_id,
            MissedCallEvent.business_id == business_id,
        )
    ).scalar_one_or_none()
    if event is None:
        return jsonify({"error": "Missed-call event not found."}), 404

    payload = request.get_json(silent=True) or {}
    archive = payload.get("archive")
    if not isinstance(archive, bool):
        return jsonify(
            {"error": "Validation failed.", "fields": {"archive": "Must be true or false."}}
        ), 400

    from datetime import datetime, timezone

    event.archived_at = datetime.now(timezone.utc) if archive else None
    event.archived_by_user_id = g.current_user.id if archive else None
    record_audit_event(
        g.db,
        action="missed_call.update",
        target_type="missed_call_event",
        target_id=str(event.id),
        business_id=business_id,
        actor_user_id=g.current_user.id,
        details={"archived": archive},
    )
    g.db.commit()
    return jsonify({"event": missed_call_dto(event)}), 200


@client_bp.get("/businesses/<business_id>/settings")
@require_business_access()
@require_module("settings")
def get_settings(business_id: str):
    business = g.db.get(Business, business_id)
    if business is None:
        return jsonify({"error": "Business not found."}), 404
    return jsonify(
        {
            "business": business_dto(business),
            "calendar": calendar_service.connection_dto(business),
        }
    ), 200


@client_bp.patch("/businesses/<business_id>/settings")
@require_business_access(write=True)
@require_module("settings")
def update_settings(business_id: str):
    """Only safe, client-editable fields. Slug, status, and numbers are admin-only."""
    business = g.db.get(Business, business_id)
    if business is None:
        return jsonify({"error": "Business not found."}), 404

    payload = request.get_json(silent=True) or {}
    changed = {}

    if "name" in payload:
        name = (payload.get("name") or "").strip()
        if not name:
            return jsonify({"error": "Validation failed.", "fields": {"name": "Required."}}), 400
        business.name = name
        changed["name"] = name

    if "business_hours" in payload and isinstance(payload["business_hours"], dict):
        settings = dict(business.settings or {})
        settings["business_hours"] = payload["business_hours"]
        business.settings = settings
        changed["business_hours"] = "updated"

    record_audit_event(
        g.db,
        action="business.settings.update",
        target_type="business",
        target_id=business_id,
        business_id=business_id,
        actor_user_id=g.current_user.id,
        details=changed,
    )
    g.db.commit()
    return jsonify({"business": business_dto(business)}), 200
