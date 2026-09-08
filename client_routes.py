"""Client Dashboard API. Scoped to one business the caller is a member of."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, select

from modules import entitlements
from modules.auth.decorators import require_business_access, require_module
from modules.models import Business, Lead, MissedCallEvent
from modules.serializers import business_dto
from modules.tenancy import record_audit_event

client_bp = Blueprint("client", __name__, url_prefix="/api/dashboard")


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

    return jsonify(
        {
            "metrics": {
                "total_leads": lead_count,
                "new_leads": open_leads,
                "missed_calls_handled": missed_calls,
            },
            "unavailable": [
                {"key": "response_rate", "reason": "Available once conversations ship in Phase 2."},
                {"key": "appointments", "reason": "Available once conversations ship in Phase 2."},
            ],
        }
    ), 200


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
