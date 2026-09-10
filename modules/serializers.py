"""Explicit response DTOs.

Allow-list, never a blanket dump of an ORM row. Nothing here may emit
password_hash, token_hash, csrf_hash, ip_hash, or any provider credential.
"""

from __future__ import annotations

from datetime import datetime

from modules.auth.decorators import platform_role


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def user_dto(user) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "platform_role": platform_role(user),
        "is_active": user.is_active,
        "created_at": _iso(user.created_at),
    }


def business_dto(business, *, module_keys: list[str] | None = None) -> dict:
    settings = business.settings or {}
    intake = settings.get("intake") or {}
    return {
        "id": business.id,
        "name": business.name,
        "slug": business.slug,
        "status": business.status,
        "default_profile_key": business.default_profile_key,
        "is_demo": bool(intake.get("demo_disclaimer", False)),
        "selection_mode": intake.get("selection_mode", "single"),
        "enabled_profiles": intake.get("enabled_profiles", []),
        "modules": module_keys or [],
        "created_at": _iso(business.created_at),
        "updated_at": _iso(business.updated_at),
    }


def phone_number_dto(number) -> dict:
    return {
        "id": number.id,
        "business_id": number.business_id,
        "phone": number.phone,
        "label": number.label,
        "enabled": number.enabled,
        "created_at": _iso(number.created_at),
    }


def missed_call_dto(event) -> dict:
    return {
        "id": event.id,
        "caller_phone": event.caller_phone,
        "twilio_number": event.twilio_number,
        "forwarded_from": event.forwarded_from,
        "source": event.source,
        "decision": event.decision,
        "message_sid": event.message_sid,
        "archived_at": _iso(event.archived_at),
        "created_at": _iso(event.created_at),
    }


def membership_dto(membership, *, user=None) -> dict:
    payload = {
        "id": membership.id,
        "business_id": membership.business_id,
        "user_id": membership.user_id,
        "role": membership.role,
        "created_at": _iso(membership.created_at),
    }
    if user is not None:
        payload["user"] = user_dto(user)
    return payload


def audit_event_dto(event) -> dict:
    return {
        "id": event.id,
        "business_id": event.business_id,
        "actor_user_id": event.actor_user_id,
        "action": event.action,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "details": event.details or {},
        "created_at": _iso(event.created_at),
    }


def lead_dto(lead) -> dict:
    """Client-safe lead representation for the lead-management workspace."""
    fields = lead.fields or {}
    return {
        "id": lead.id,
        "phone": lead.phone,
        "profile_key": lead.profile_key,
        "customer_name": fields.get("name") or fields.get("customer_name"),
        "service_request": fields.get("service_request") or fields.get("service"),
        "source": fields.get("source"),
        "intake_data": fields,
        "intake_status": lead.status,
        "workflow_status": lead.workflow_status,
        "category": lead.category,
        "business_summary": lead.business_summary,
        "client_notes": lead.client_notes,
        "requested_callback_time": lead.requested_callback_time,
        "is_complete": lead.is_complete,
        "archived_at": _iso(lead.archived_at),
        "created_at": _iso(lead.created_at),
        "updated_at": _iso(lead.updated_at),
    }


def _conversation_fields(row) -> dict:
    """Drop private workflow keys while preserving client-owned intake data."""
    fields = row.fields or {}
    if not isinstance(fields, dict):
        return {}
    return {key: value for key, value in fields.items() if not str(key).startswith("__")}


def _conversation_messages(row) -> list[dict]:
    messages = []
    for item in row.history if isinstance(row.history, list) else []:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        messages.append({"role": role, "content": content})
    return messages


def conversation_summary_dto(row) -> dict:
    fields = _conversation_fields(row)
    messages = _conversation_messages(row)
    last_message = next(
        (item["content"] for item in reversed(messages)),
        "",
    )
    return {
        "id": row.id,
        "phone": row.phone,
        "customer_name": fields.get("name") or fields.get("customer_name"),
        "profile_key": row.profile_key,
        "state": row.state,
        "turn_count": row.turn_count,
        "off_topic_strikes": row.off_topic_strikes,
        "terminated": row.terminated,
        "opted_out": row.opted_out,
        "requested_callback_time": row.requested_callback_time,
        "message_count": len(messages),
        "last_message": last_message[:240],
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "expires_at": _iso(row.expires_at),
    }


def conversation_detail_dto(row) -> dict:
    payload = conversation_summary_dto(row)
    payload["messages"] = _conversation_messages(row)
    payload["collected_fields"] = _conversation_fields(row)
    return payload


def session_dto(row) -> dict:
    """Deliberately omits token_hash, csrf_hash, and ip_hash."""
    return {
        "id": row.id,
        "user_id": row.user_id,
        "created_at": _iso(row.created_at),
        "last_activity_at": _iso(row.last_activity_at),
        "expires_at": _iso(row.expires_at),
        "revoked_at": _iso(row.revoked_at),
        "user_agent": row.user_agent,
    }
