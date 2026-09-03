"""
models.py
SQLAlchemy ORM models backing persistent conversation state.

Tables:
  conversation_sessions - one row per active/expired phone-number session
  leads                 - one row per completed or escalated intake
  processed_messages    - Twilio MessageSid ledger for webhook idempotency
  missed_call_events    - forwarded-call follow-up ledger and CallSid idempotency
"""

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String, Text, Integer, Boolean, DateTime, JSON, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from modules.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ConversationSession(Base):
    __tablename__ = "conversation_sessions"
    __table_args__ = (
        UniqueConstraint("business_id", "phone", name="uq_conversation_sessions_business_phone"),
        Index("ix_conversation_sessions_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)

    # "awaiting_profile_selection" (demo only) | "in_progress" | "completed" | "terminated"
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="awaiting_profile_selection")
    profile_key: Mapped[str | None] = mapped_column(String(32), nullable=True)

    history: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    fields: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    off_topic_strikes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    terminated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    opted_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    requested_callback_time: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_message_sid: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Null only while the legacy demo rows are being backfilled by the
    # multi-tenant migration. Every new platform session is business-scoped.
    business_id: Mapped[str | None] = mapped_column(
        ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=True, index=True
    )


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (Index("ix_leads_phone", "phone"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_key: Mapped[str] = mapped_column(String(32), nullable=False)

    fields: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # "completed" | "escalated" (off_topic/unsafe/max_turns/error)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    business_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    termination_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)

    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    off_topic_strikes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    requested_callback_time: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Dashboard workflow is independent of intake completion/escalation status.
    workflow_status: Mapped[str] = mapped_column(String(32), nullable=False, default="new")
    client_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    business_id: Mapped[str | None] = mapped_column(
        ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=True, index=True
    )


class ProcessedMessage(Base):
    """
    Idempotency ledger. Twilio may retry a webhook delivery (timeout, 5xx,
    etc.) with the same MessageSid; we must not process it twice or send a
    duplicate reply / create a duplicate lead.
    """
    __tablename__ = "processed_messages"
    __table_args__ = (UniqueConstraint("message_sid", name="uq_processed_messages_sid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_sid: Mapped[str] = mapped_column(String(64), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)

    # The TwiML response body we sent, so a retried request can be answered
    # identically without re-running the whole pipeline (OpenAI, DB writes).
    response_body: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    business_id: Mapped[str | None] = mapped_column(
        ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=True, index=True
    )


class MissedCallEvent(Base):
    """One row for every Twilio Voice webhook received by /voice/missed-call.

    ``call_sid`` is unique, so a Twilio retry—or two Gunicorn workers racing
    to handle the same webhook—cannot trigger two initial text messages.
    """

    __tablename__ = "missed_call_events"
    __table_args__ = (
        UniqueConstraint("call_sid", name="uq_missed_call_events_call_sid"),
        Index("ix_missed_call_events_caller_created", "caller_phone", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_sid: Mapped[str] = mapped_column(String(64), nullable=False)
    caller_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    twilio_number: Mapped[str] = mapped_column(String(32), nullable=False)
    forwarded_from: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="missed_call")
    decision: Mapped[str] = mapped_column(String(64), nullable=False)
    message_sid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True
    )
    business_id: Mapped[str | None] = mapped_column(
        ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=True, index=True
    )


class Business(Base):
    """An isolated client tenant. IDs are generated by the platform, never by clients."""

    __tablename__ = "businesses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    default_profile_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class BusinessPhoneNumber(Base):
    """Maps an inbound Twilio number to one business (and optional location rules)."""

    __tablename__ = "business_phone_numbers"
    __table_args__ = (UniqueConstraint("phone", name="uq_business_phone_numbers_phone"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_id: Mapped[str] = mapped_column(
        ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class PlatformUser(Base):
    """A person who can sign into the dashboard.

    Business access is granted through BusinessMembership. Only a platform
    administrator can create tenants, map phone numbers, or permanently
    delete retained records.
    """

    __tablename__ = "platform_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class BusinessMembership(Base):
    """A dashboard user's role within one client business."""

    __tablename__ = "business_memberships"
    __table_args__ = (UniqueConstraint("business_id", "user_id", name="uq_business_membership"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_id: Mapped[str] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("platform_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # owner | manager | staff | viewer. This is intentionally separate from
    # the platform-admin flag so a client owner never gains cross-tenant power.
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="owner")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class AuditEvent(Base):
    """Append-only record of sensitive dashboard actions and retention changes."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_business_created", "business_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_id: Mapped[str | None] = mapped_column(
        ForeignKey("businesses.id", ondelete="SET NULL"), nullable=True
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(96), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
