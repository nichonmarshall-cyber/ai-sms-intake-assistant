"""Control Center API. Platform administrators only."""

from __future__ import annotations

import logging
import re
from uuid import uuid4

from flask import Blueprint, g, jsonify, request
from sqlalchemy import String, cast, func, or_, select

from modules import entitlements
from modules.auth import passwords, sessions
from modules.auth.decorators import require_platform_admin, require_platform_operator
from modules.conversation_store import normalize_phone
from modules.models import (
    AuditEvent,
    Business,
    BusinessMembership,
    BusinessPhoneNumber,
    ConversationSession,
    Lead,
    MissedCallEvent,
    PlatformUser,
    ProcessedMessage,
)
from modules.serializers import (
    audit_event_dto,
    business_dto,
    conversation_summary_dto,
    membership_dto,
    missed_call_dto,
    phone_number_dto,
    user_dto,
)
from modules.tenancy import assign_phone_number, record_audit_event

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
VALID_MEMBERSHIP_ROLES = {"owner", "manager", "staff", "viewer"}
VALID_PLATFORM_ROLES = {"none", "staff", "admin"}
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


@admin_bp.get("/businesses")
@require_platform_operator
def list_businesses():
    page, size = _page_args()
    search = (request.args.get("q") or "").strip().lower()
    status = (request.args.get("status") or "").strip().lower()

    query = select(Business)
    if search:
        query = query.where(func.lower(Business.name).like(f"%{search}%"))
    if status:
        query = query.where(Business.status == status)

    total = g.db.execute(
        select(func.count()).select_from(query.subquery())
    ).scalar_one()

    rows = list(
        g.db.execute(
            query.order_by(Business.name).offset((page - 1) * size).limit(size)
        ).scalars()
    )

    items = []
    for business in rows:
        module_keys = sorted(entitlements.enabled_module_keys(g.db, business.id))
        items.append(business_dto(business, module_keys=module_keys))

    return jsonify({"items": items, "total": total, "page": page, "page_size": size}), 200


@admin_bp.post("/businesses")
@require_platform_admin
def create_business_route():
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    slug = (payload.get("slug") or "").strip().lower()

    errors = {}
    if not name:
        errors["name"] = "Business name is required."
    if not SLUG_PATTERN.match(slug or ""):
        errors["slug"] = "Slug must be lowercase words separated by hyphens."
    if errors:
        return jsonify({"error": "Validation failed.", "fields": errors}), 400

    existing = g.db.execute(select(Business).where(Business.slug == slug)).scalar_one_or_none()
    if existing is not None:
        return jsonify({"error": "That slug is already in use.", "fields": {"slug": "Already taken."}}), 409

    business = Business(
        id=str(uuid4()),
        name=name,
        slug=slug,
        status="active",
        default_profile_key=(payload.get("default_profile_key") or None),
        settings=payload.get("settings") or {},
    )
    g.db.add(business)
    g.db.flush()

    entitlements.apply_defaults(g.db, business.id)
    record_audit_event(
        g.db,
        action="business.create",
        target_type="business",
        target_id=business.id,
        business_id=business.id,
        actor_user_id=g.current_user.id,
        details={"name": name, "slug": slug},
    )
    g.db.commit()

    module_keys = sorted(entitlements.enabled_module_keys(g.db, business.id))
    return jsonify(business_dto(business, module_keys=module_keys)), 201


@admin_bp.get("/businesses/<business_id>")
@require_platform_operator
def get_business(business_id: str):
    business = g.db.get(Business, business_id)
    if business is None:
        return jsonify({"error": "Business not found."}), 404

    numbers = list(
        g.db.execute(
            select(BusinessPhoneNumber).where(BusinessPhoneNumber.business_id == business_id)
        ).scalars()
    )
    memberships = list(
        g.db.execute(
            select(BusinessMembership).where(BusinessMembership.business_id == business_id)
        ).scalars()
    )
    enabled = entitlements.enabled_module_keys(g.db, business_id)

    return jsonify(
        {
            "business": business_dto(business, module_keys=sorted(enabled)),
            "phone_numbers": [phone_number_dto(n) for n in numbers],
            "memberships": [
                membership_dto(m, user=g.db.get(PlatformUser, m.user_id)) for m in memberships
            ],
            "modules": [
                {
                    "key": spec.key,
                    "label": spec.label,
                    "icon": spec.icon,
                    "implemented": spec.implemented,
                    "description": spec.description,
                    "enabled": spec.key in enabled,
                }
                for spec in entitlements.MODULE_REGISTRY
            ],
            "counts": {
                "leads": g.db.execute(
                    select(func.count()).select_from(Lead).where(Lead.business_id == business_id)
                ).scalar_one(),
                "missed_calls": g.db.execute(
                    select(func.count())
                    .select_from(MissedCallEvent)
                    .where(MissedCallEvent.business_id == business_id)
                ).scalar_one(),
            },
        }
    ), 200


@admin_bp.patch("/businesses/<business_id>")
@require_platform_admin
def update_business(business_id: str):
    business = g.db.get(Business, business_id)
    if business is None:
        return jsonify({"error": "Business not found."}), 404

    payload = request.get_json(silent=True) or {}
    changed = {}

    if "name" in payload:
        name = (payload.get("name") or "").strip()
        if not name:
            return jsonify({"error": "Validation failed.", "fields": {"name": "Required."}}), 400
        changed["name"] = name
        business.name = name

    if "status" in payload:
        status = (payload.get("status") or "").strip().lower()
        if status not in {"active", "suspended"}:
            return jsonify({"error": "Validation failed.", "fields": {"status": "Invalid."}}), 400
        changed["status"] = status
        business.status = status

    if "settings" in payload and isinstance(payload["settings"], dict):
        business.settings = payload["settings"]
        changed["settings"] = "updated"

    if "default_profile_key" in payload:
        business.default_profile_key = payload.get("default_profile_key") or None
        changed["default_profile_key"] = business.default_profile_key

    record_audit_event(
        g.db,
        action="business.update",
        target_type="business",
        target_id=business_id,
        business_id=business_id,
        actor_user_id=g.current_user.id,
        details=changed,
    )
    g.db.commit()

    module_keys = sorted(entitlements.enabled_module_keys(g.db, business_id))
    return jsonify(business_dto(business, module_keys=module_keys)), 200


@admin_bp.put("/businesses/<business_id>/modules/<module_key>")
@require_platform_admin
def set_business_module(business_id: str, module_key: str):
    business = g.db.get(Business, business_id)
    if business is None:
        return jsonify({"error": "Business not found."}), 404
    if not entitlements.is_valid_module(module_key):
        return jsonify({"error": "Unknown module."}), 404

    payload = request.get_json(silent=True) or {}
    enabled = bool(payload.get("enabled", False))

    entitlements.set_module(g.db, business_id, module_key, enabled)
    record_audit_event(
        g.db,
        action="business.module.update",
        target_type="business_module",
        target_id=module_key,
        business_id=business_id,
        actor_user_id=g.current_user.id,
        details={"module": module_key, "enabled": enabled},
    )
    g.db.commit()

    return jsonify({"module_key": module_key, "enabled": enabled}), 200


@admin_bp.post("/businesses/<business_id>/phone-numbers")
@require_platform_admin
def add_phone_number(business_id: str):
    business = g.db.get(Business, business_id)
    if business is None:
        return jsonify({"error": "Business not found."}), 404

    payload = request.get_json(silent=True) or {}
    phone = (payload.get("phone") or "").strip()
    normalized = normalize_phone(phone)
    digits = normalized.removeprefix("+")
    if not normalized or not digits.isdigit() or not 10 <= len(digits) <= 15:
        return jsonify(
            {
                "error": "Validation failed.",
                "fields": {"phone": "Enter a valid 10–15 digit phone number."},
            }
        ), 400

    existing = g.db.execute(
        select(BusinessPhoneNumber).where(BusinessPhoneNumber.phone == normalized)
    ).scalar_one_or_none()
    if existing is not None:
        return jsonify(
            {
                "error": "That phone number is already assigned.",
                "fields": {"phone": "Already assigned to another tenant."},
            }
        ), 409

    number = assign_phone_number(
        g.db,
        business_id=business_id,
        phone=phone,
        label=payload.get("label"),
        settings=payload.get("settings") or {},
    )
    record_audit_event(
        g.db,
        action="business.phone_number.assign",
        target_type="business_phone_number",
        target_id=str(number.id),
        business_id=business_id,
        actor_user_id=g.current_user.id,
        details={"phone": number.phone},
    )
    g.db.commit()
    return jsonify(phone_number_dto(number)), 201


@admin_bp.patch("/businesses/<business_id>/phone-numbers/<int:number_id>")
@require_platform_admin
def update_phone_number(business_id: str, number_id: int):
    number = g.db.execute(
        select(BusinessPhoneNumber).where(
            BusinessPhoneNumber.id == number_id,
            BusinessPhoneNumber.business_id == business_id,
        )
    ).scalar_one_or_none()
    if number is None:
        return jsonify({"error": "Phone number not found."}), 404

    payload = request.get_json(silent=True) or {}
    changed = {}
    if "label" in payload:
        number.label = (payload.get("label") or "").strip() or None
        changed["label"] = number.label
    if "enabled" in payload:
        if not isinstance(payload["enabled"], bool):
            return jsonify(
                {"error": "Validation failed.", "fields": {"enabled": "Must be true or false."}}
            ), 400
        number.enabled = payload["enabled"]
        changed["enabled"] = number.enabled
    if not changed:
        return jsonify({"error": "No supported changes were supplied."}), 400

    record_audit_event(
        g.db,
        action="business.phone_number.update",
        target_type="business_phone_number",
        target_id=str(number.id),
        business_id=business_id,
        actor_user_id=g.current_user.id,
        details=changed,
    )
    g.db.commit()
    return jsonify(phone_number_dto(number)), 200


@admin_bp.get("/users")
@require_platform_operator
def list_users():
    rows = list(g.db.execute(select(PlatformUser).order_by(PlatformUser.email)).scalars())
    return jsonify({"items": [user_dto(u) for u in rows]}), 200


@admin_bp.post("/users")
@require_platform_admin
def create_user():
    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    role = (payload.get("platform_role") or "none").strip().lower()

    errors = {}
    if "@" not in email:
        errors["email"] = "A valid email is required."
    strength_error = passwords.validate_password_strength(password)
    if strength_error:
        errors["password"] = strength_error
    if role not in VALID_PLATFORM_ROLES:
        errors["platform_role"] = "Invalid role."
    if errors:
        return jsonify({"error": "Validation failed.", "fields": errors}), 400

    existing = g.db.execute(
        select(PlatformUser).where(PlatformUser.email == email)
    ).scalar_one_or_none()
    if existing is not None:
        return jsonify({"error": "That email is already registered."}), 409

    user = PlatformUser(
        id=str(uuid4()),
        email=email,
        display_name=(payload.get("display_name") or "").strip() or None,
        password_hash=passwords.hash_password(password),
        platform_role=role,
        is_platform_admin=(role == "admin"),
        is_active=True,
    )
    g.db.add(user)
    g.db.flush()

    record_audit_event(
        g.db,
        action="user.create",
        target_type="platform_user",
        target_id=user.id,
        actor_user_id=g.current_user.id,
        details={"email": email, "platform_role": role},
    )
    g.db.commit()
    return jsonify(user_dto(user)), 201


@admin_bp.post("/businesses/<business_id>/memberships")
@require_platform_admin
def create_membership(business_id: str):
    business = g.db.get(Business, business_id)
    if business is None:
        return jsonify({"error": "Business not found."}), 404

    payload = request.get_json(silent=True) or {}
    user_id = (payload.get("user_id") or "").strip()
    role = (payload.get("role") or "owner").strip().lower()

    if role not in VALID_MEMBERSHIP_ROLES:
        return jsonify({"error": "Validation failed.", "fields": {"role": "Invalid role."}}), 400

    user = g.db.get(PlatformUser, user_id)
    if user is None:
        return jsonify({"error": "User not found."}), 404

    existing = g.db.execute(
        select(BusinessMembership).where(
            BusinessMembership.business_id == business_id,
            BusinessMembership.user_id == user_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.role = role
        membership = existing
    else:
        membership = BusinessMembership(business_id=business_id, user_id=user_id, role=role)
        g.db.add(membership)
    g.db.flush()

    record_audit_event(
        g.db,
        action="membership.upsert",
        target_type="business_membership",
        target_id=str(membership.id),
        business_id=business_id,
        actor_user_id=g.current_user.id,
        details={"user_id": user_id, "role": role},
    )
    g.db.commit()
    return jsonify(membership_dto(membership, user=user)), 201


@admin_bp.delete("/businesses/<business_id>/memberships/<int:membership_id>")
@require_platform_admin
def delete_membership(business_id: str, membership_id: int):
    membership = g.db.execute(
        select(BusinessMembership).where(
            BusinessMembership.id == membership_id,
            BusinessMembership.business_id == business_id,
        )
    ).scalar_one_or_none()
    if membership is None:
        return jsonify({"error": "Membership not found."}), 404

    record_audit_event(
        g.db,
        action="membership.remove",
        target_type="business_membership",
        target_id=str(membership.id),
        business_id=business_id,
        actor_user_id=g.current_user.id,
        details={"user_id": membership.user_id, "role": membership.role},
    )
    g.db.delete(membership)
    g.db.commit()
    return "", 204


@admin_bp.post("/users/<user_id>/revoke-sessions")
@require_platform_admin
def revoke_user_sessions(user_id: str):
    user = g.db.get(PlatformUser, user_id)
    if user is None:
        return jsonify({"error": "User not found."}), 404

    count = sessions.revoke_all_for_user(g.db, user_id)
    record_audit_event(
        g.db,
        action="user.sessions.revoke",
        target_type="platform_user",
        target_id=user_id,
        actor_user_id=g.current_user.id,
        details={"revoked": count},
    )
    g.db.commit()
    return jsonify({"revoked": count}), 200


@admin_bp.get("/audit-events")
@require_platform_operator
def list_audit_events():
    page, size = _page_args()
    business_id = (request.args.get("business_id") or "").strip()

    query = select(AuditEvent)
    if business_id:
        query = query.where(AuditEvent.business_id == business_id)

    total = g.db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = list(
        g.db.execute(
            query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        ).scalars()
    )
    return jsonify(
        {
            "items": [audit_event_dto(e) for e in rows],
            "total": total,
            "page": page,
            "page_size": size,
        }
    ), 200


@admin_bp.get("/overview")
@require_platform_operator
def platform_overview():
    """Only metrics backed by real tables. No fabricated numbers."""
    total_businesses = g.db.execute(
        select(func.count()).select_from(Business).where(Business.status == "active")
    ).scalar_one()
    total_leads = g.db.execute(select(func.count()).select_from(Lead)).scalar_one()
    total_missed = g.db.execute(select(func.count()).select_from(MissedCallEvent)).scalar_one()
    total_users = g.db.execute(select(func.count()).select_from(PlatformUser)).scalar_one()

    return jsonify(
        {
            "active_businesses": total_businesses,
            "leads": total_leads,
            "missed_calls": total_missed,
            "users": total_users,
            "unavailable": [
                {"key": "websites_online", "reason": "No monitoring provider configured."},
                {"key": "sms_usage", "reason": "Twilio usage API not connected."},
                {"key": "active_alerts", "reason": "Alerts arrive in Phase 3."},
            ],
        }
    ), 200


@admin_bp.get("/conversations")
@require_platform_operator
def platform_conversations():
    page, size = _page_args()
    search = (request.args.get("q") or "").strip().lower()
    state = (request.args.get("state") or "").strip().lower()
    valid_states = {"awaiting_profile_selection", "in_progress", "completed", "terminated"}
    if state and state not in valid_states:
        return jsonify({"error": "Invalid conversation state."}), 400

    query = (
        select(ConversationSession, Business)
        .join(Business, ConversationSession.business_id == Business.id)
    )
    if state:
        query = query.where(ConversationSession.state == state)
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                func.lower(ConversationSession.phone).like(pattern),
                func.lower(Business.name).like(pattern),
                func.lower(cast(ConversationSession.fields, String)).like(pattern),
            )
        )

    total = g.db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = g.db.execute(
        query.order_by(ConversationSession.updated_at.desc(), ConversationSession.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    items = []
    for session, business in rows:
        item = conversation_summary_dto(session)
        item["business"] = {"id": business.id, "name": business.name, "slug": business.slug}
        items.append(item)
    return jsonify(
        {
            "items": items,
            "total": total,
            "page": page,
            "page_size": size,
            "states": sorted(valid_states),
        }
    ), 200


@admin_bp.get("/delivery")
@require_platform_operator
def platform_delivery():
    rows = g.db.execute(
        select(MissedCallEvent, Business)
        .join(Business, MissedCallEvent.business_id == Business.id)
        .order_by(MissedCallEvent.created_at.desc(), MissedCallEvent.id.desc())
        .limit(100)
    ).all()
    total = g.db.execute(select(func.count()).select_from(MissedCallEvent)).scalar_one()
    queued = g.db.execute(
        select(func.count())
        .select_from(MissedCallEvent)
        .where(MissedCallEvent.message_sid.is_not(None))
    ).scalar_one()
    items = []
    for event, business in rows:
        item = missed_call_dto(event)
        item["business"] = {"id": business.id, "name": business.name}
        item["delivery_status"] = "queued" if event.message_sid else "not_sent"
        items.append(item)
    return jsonify(
        {
            "metrics": {"attempted": total, "queued": queued, "not_sent": total - queued},
            "items": items,
            "notice": "Provider delivery receipts are not stored yet; queued does not mean delivered.",
        }
    ), 200


@admin_bp.get("/webhooks")
@require_platform_operator
def platform_webhooks():
    businesses = {
        business.id: business.name
        for business in g.db.execute(select(Business)).scalars()
    }
    sms_rows = list(
        g.db.execute(
            select(ProcessedMessage)
            .order_by(ProcessedMessage.created_at.desc(), ProcessedMessage.id.desc())
            .limit(100)
        ).scalars()
    )
    voice_rows = list(
        g.db.execute(
            select(MissedCallEvent)
            .order_by(MissedCallEvent.created_at.desc(), MissedCallEvent.id.desc())
            .limit(100)
        ).scalars()
    )
    items = [
        {
            "id": f"sms-{row.id}",
            "kind": "Inbound SMS",
            "business_id": row.business_id,
            "business_name": businesses.get(row.business_id, "Legacy or unassigned"),
            "external_id": row.message_sid,
            "phone": row.phone,
            "outcome": "processed",
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in sms_rows
    ] + [
        {
            "id": f"voice-{row.id}",
            "kind": "Voice webhook",
            "business_id": row.business_id,
            "business_name": businesses.get(row.business_id, "Legacy or unassigned"),
            "external_id": row.call_sid,
            "phone": row.caller_phone,
            "outcome": row.decision,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in voice_rows
    ]
    items.sort(key=lambda item: (item["created_at"] or "", item["id"]), reverse=True)
    return jsonify(
        {
            "metrics": {
                "inbound_sms": len(sms_rows),
                "voice_events": len(voice_rows),
                "total_recent": min(len(items), 100),
            },
            "items": items[:100],
            "notice": "This is the persisted idempotency ledger, not raw request payloads.",
        }
    ), 200
