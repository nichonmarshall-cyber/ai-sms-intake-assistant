"""Client Dashboard API. Scoped to one business the caller is a member of."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request
from sqlalchemy import String, cast, func, or_, select

from modules import entitlements
from modules.auth.decorators import require_business_access, require_module
from modules.models import Business, ConversationSession, Lead, MissedCallEvent
from modules.serializers import (
    business_dto,
    conversation_detail_dto,
    conversation_summary_dto,
    lead_dto,
)
from modules.tenancy import record_audit_event

client_bp = Blueprint("client", __name__, url_prefix="/api/dashboard")

LEAD_WORKFLOW_STATUSES = {"new", "qualified", "needs_review", "scheduled", "closed"}
CONVERSATION_STATES = {"awaiting_profile_selection", "in_progress", "completed", "terminated"}
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

    return jsonify(
        {
            "metrics": {
                "total_leads": lead_count,
                "new_leads": open_leads,
                "open_conversations": open_conversations,
                "missed_calls_handled": missed_calls,
            },
            "unavailable": [
                {
                    "key": "response_rate",
                    "reason": "Requires provider delivery timestamps; message history alone cannot calculate it.",
                },
                {"key": "appointments", "reason": "Calendar scheduling is not connected yet."},
            ],
        }
    ), 200


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


@client_bp.get("/businesses/<business_id>/settings")
@require_business_access()
@require_module("settings")
def get_settings(business_id: str):
    business = g.db.get(Business, business_id)
    if business is None:
        return jsonify({"error": "Business not found."}), 404
    return jsonify({"business": business_dto(business)}), 200


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
