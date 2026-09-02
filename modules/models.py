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

from sqlalchemy import String, Integer, Boolean, DateTime, JSON, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from modules.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ConversationSession(Base):
    __tablename__ = "conversation_sessions"
    __table_args__ = (
        UniqueConstraint("phone", name="uq_conversation_sessions_phone"),
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

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
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
