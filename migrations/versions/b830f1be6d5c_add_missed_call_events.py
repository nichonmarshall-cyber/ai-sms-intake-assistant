"""add missed call events

Revision ID: b830f1be6d5c
Revises: 7d2686ad5b0c
Create Date: 2026-09-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b830f1be6d5c"
down_revision: Union[str, None] = "7d2686ad5b0c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "missed_call_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("call_sid", sa.String(length=64), nullable=False),
        sa.Column("caller_phone", sa.String(length=32), nullable=False),
        sa.Column("twilio_number", sa.String(length=32), nullable=False),
        sa.Column("forwarded_from", sa.String(length=32), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=64), nullable=False),
        sa.Column("message_sid", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("call_sid", name="uq_missed_call_events_call_sid"),
    )
    op.create_index(
        "ix_missed_call_events_caller_created",
        "missed_call_events",
        ["caller_phone", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_missed_call_events_caller_created", table_name="missed_call_events")
    op.drop_table("missed_call_events")
