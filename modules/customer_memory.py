"""Tenant-scoped customer memory with bounded summaries and approval gates."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from modules.conversation_store import normalize_phone
from modules.models import (
    AppointmentRequest,
    CustomerMemory,
    CustomerMemoryRecord,
    Lead,
    MemoryUpdateProposal,
)
from modules.module_configuration import get_configuration


class MemoryValidationError(ValueError):
    pass


def _record_schema(db: DBSession, business_id: str, record_type: str) -> dict:
    config, _ = get_configuration(db, business_id, "ai_memory")
    for item in config["record_types"]:
        if item["key"] == record_type:
            return item
    raise MemoryValidationError("That record type is not configured for this business.")


def _clean_values(schema: dict, values: dict, *, ai_proposal: bool = False) -> dict:
    if not isinstance(values, dict):
        raise MemoryValidationError("values must be an object.")
    definitions = {field["key"]: field for field in schema["fields"]}
    unknown = set(values) - set(definitions)
    if unknown:
        raise MemoryValidationError(f"Unknown field: {sorted(unknown)[0]}.")
    cleaned = {}
    for key, value in values.items():
        field = definitions[key]
        if ai_proposal and (
            field["ai_visibility"] != "proposed_update"
            or field["update_authority"] not in {"ai_proposal", "deterministic_rule"}
        ):
            raise MemoryValidationError(f"The AI is not allowed to propose changes to {key}.")
        if field["sensitivity"] == "restricted" and ai_proposal:
            raise MemoryValidationError("Restricted fields cannot be proposed by AI.")
        if value is None or value == "":
            cleaned[key] = None
        elif field["type"] == "boolean":
            if not isinstance(value, bool):
                raise MemoryValidationError(f"{key} must be true or false.")
            cleaned[key] = value
        elif field["type"] == "number":
            if isinstance(value, bool):
                raise MemoryValidationError(f"{key} must be a number.")
            try:
                cleaned[key] = float(value)
            except (TypeError, ValueError) as exc:
                raise MemoryValidationError(f"{key} must be a number.") from exc
        else:
            text = str(value).strip()
            if len(text) > 2000:
                raise MemoryValidationError(f"{key} cannot exceed 2000 characters.")
            if field["type"] == "choice" and text not in field["choices"]:
                raise MemoryValidationError(f"{key} must be one of its configured choices.")
            cleaned[key] = text
    return cleaned


def get_or_create_customer(
    db: DBSession, business_id: str, phone: str, *, customer_name: str | None = None
) -> CustomerMemory:
    phone = normalize_phone(phone)
    if not phone:
        raise MemoryValidationError("A customer phone number is required.")
    row = db.execute(select(CustomerMemory).where(
        CustomerMemory.business_id == business_id, CustomerMemory.phone == phone
    )).scalar_one_or_none()
    if row is None:
        row = CustomerMemory(
            business_id=business_id,
            phone=phone,
            customer_name=(customer_name or "").strip()[:160] or None,
        )
        db.add(row)
        db.flush()
    elif customer_name and not row.customer_name:
        row.customer_name = customer_name.strip()[:160]
    return row


def rebuild_summary(db: DBSession, customer: CustomerMemory) -> str:
    """Build a deterministic bounded summary; model summarization can replace this later."""
    config, _ = get_configuration(db, customer.business_id, "ai_memory")
    if not config["rolling_summary_enabled"]:
        customer.rolling_summary = ""
        return ""
    leads = list(db.execute(select(Lead).where(
        Lead.business_id == customer.business_id, Lead.phone == customer.phone
    ).order_by(Lead.created_at.desc()).limit(5)).scalars())
    appointments = list(db.execute(select(AppointmentRequest).where(
        AppointmentRequest.business_id == customer.business_id,
        AppointmentRequest.customer_phone == customer.phone,
    ).order_by(AppointmentRequest.created_at.desc()).limit(3)).scalars())
    parts = []
    if customer.customer_name:
        parts.append(f"Customer: {customer.customer_name}.")
    for lead in leads:
        description = lead.business_summary or (lead.fields or {}).get("service_request")
        if description:
            parts.append(f"Request: {str(description).strip()} ({lead.workflow_status}).")
    for appointment in appointments:
        when = appointment.scheduled_start_at.isoformat() if appointment.scheduled_start_at else appointment.requested_time_text
        parts.append(f"Appointment: {appointment.status}{f' at {when}' if when else ''}.")
    summary = " ".join(parts)[:config["summary_max_characters"]]
    customer.rolling_summary = summary
    customer.summary_source_count = len(leads) + len(appointments)
    customer.summary_updated_at = datetime.now(timezone.utc)
    return summary


def create_record(db: DBSession, customer: CustomerMemory, payload: dict) -> CustomerMemoryRecord:
    record_type = str(payload.get("record_type") or "").strip().lower()
    schema = _record_schema(db, customer.business_id, record_type)
    values = _clean_values(schema, payload.get("values") or {})
    label = str(payload.get("label") or schema["label"]).strip()[:160]
    if not label:
        raise MemoryValidationError("A record label is required.")
    row = CustomerMemoryRecord(
        business_id=customer.business_id,
        customer_memory_id=customer.id,
        record_type=record_type,
        label=label,
        values=values,
        status=(str(payload.get("status") or "").strip().lower() or None),
    )
    db.add(row)
    db.flush()
    return row


def update_record(db: DBSession, row: CustomerMemoryRecord, payload: dict) -> CustomerMemoryRecord:
    expected = payload.get("expected_version")
    if expected is not None and int(expected) != row.version:
        raise MemoryValidationError("This record changed after you opened it. Refresh and try again.")
    schema = _record_schema(db, row.business_id, row.record_type)
    if "values" in payload:
        row.values = {**(row.values or {}), **_clean_values(schema, payload["values"])}
    if "label" in payload:
        row.label = str(payload["label"] or "").strip()[:160]
        if not row.label:
            raise MemoryValidationError("A record label is required.")
    if "status" in payload:
        row.status = str(payload["status"] or "").strip().lower() or None
    row.version += 1
    return row


def propose_update(
    db: DBSession, customer: CustomerMemory, payload: dict, *, source_session_id: int | None = None
) -> MemoryUpdateProposal:
    record_type = str(payload.get("record_type") or "").strip().lower()
    schema = _record_schema(db, customer.business_id, record_type)
    values = _clean_values(schema, payload.get("proposed_values") or {}, ai_proposal=True)
    row = MemoryUpdateProposal(
        business_id=customer.business_id,
        customer_memory_id=customer.id,
        record_id=payload.get("record_id"),
        record_type=record_type,
        proposed_values=values,
        proposed_status=str(payload.get("proposed_status") or "").strip().lower() or None,
        reason=str(payload.get("reason") or "").strip()[:500] or None,
        source_session_id=source_session_id,
    )
    db.add(row)
    db.flush()
    return row


def context_packet(db: DBSession, business_id: str, phone: str) -> dict | None:
    customer = db.execute(select(CustomerMemory).where(
        CustomerMemory.business_id == business_id,
        CustomerMemory.phone == normalize_phone(phone),
    )).scalar_one_or_none()
    if customer is None:
        return None
    config, _ = get_configuration(db, business_id, "ai_memory")
    schemas = {item["key"]: item for item in config["record_types"]}
    records = []
    for row in db.execute(select(CustomerMemoryRecord).where(
        CustomerMemoryRecord.customer_memory_id == customer.id
    ).order_by(CustomerMemoryRecord.updated_at.desc()).limit(12)).scalars():
        schema = schemas.get(row.record_type)
        if not schema:
            continue
        visible = {field["key"] for field in schema["fields"] if field["ai_visibility"] != "hidden"}
        records.append({
            "record_type": row.record_type, "label": row.label, "status": row.status,
            "values": {key: value for key, value in (row.values or {}).items() if key in visible},
        })
    return {
        "customer_name": customer.customer_name,
        "rolling_summary": customer.rolling_summary,
        "records": records,
    }


def sync_completed_lead(db: DBSession, lead: Lead) -> CustomerMemory | None:
    if not lead.business_id:
        return None
    fields = lead.fields or {}
    customer = get_or_create_customer(
        db, lead.business_id, lead.phone,
        customer_name=fields.get("name") or fields.get("customer_name"),
    )
    rebuild_summary(db, customer)
    db.commit()
    return customer


def customer_dto(row: CustomerMemory, *, pending_proposals: int = 0) -> dict:
    return {
        "id": row.id, "phone": row.phone, "customer_name": row.customer_name,
        "rolling_summary": row.rolling_summary,
        "summary_source_count": row.summary_source_count,
        "summary_updated_at": row.summary_updated_at.isoformat() if row.summary_updated_at else None,
        "pending_proposals": pending_proposals,
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
    }


def record_dto(row: CustomerMemoryRecord) -> dict:
    return {
        "id": row.id, "customer_memory_id": row.customer_memory_id,
        "record_type": row.record_type, "label": row.label, "values": row.values or {},
        "status": row.status, "version": row.version,
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
    }


def proposal_dto(row: MemoryUpdateProposal) -> dict:
    return {
        "id": row.id, "customer_memory_id": row.customer_memory_id, "record_id": row.record_id,
        "record_type": row.record_type, "proposed_values": row.proposed_values or {},
        "proposed_status": row.proposed_status, "reason": row.reason, "status": row.status,
        "source_session_id": row.source_session_id,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "created_at": row.created_at.isoformat(),
    }
