"""add calendar appointment requests

Revision ID: e5f8a1b6c005
Revises: e4d7f0a5f004
Create Date: 2026-09-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f8a1b6c005"
down_revision: Union[str, None] = "e4d7f0a5f004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "appointment_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("customer_name", sa.String(length=160), nullable=True),
        sa.Column("customer_phone", sa.String(length=32), nullable=False),
        sa.Column("service_request", sa.String(length=500), nullable=True),
        sa.Column("requested_time_text", sa.String(length=160), nullable=True),
        sa.Column("scheduled_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), server_default="60", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("calendar_event_id", sa.String(length=255), nullable=True),
        sa.Column("calendar_event_link", sa.String(length=1000), nullable=True),
        sa.Column("provider_error", sa.String(length=255), nullable=True),
        sa.Column("scheduled_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["scheduled_by_user_id"], ["platform_users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id", "lead_id", name="uq_appointment_requests_business_lead"
        ),
    )
    op.create_index(
        "ix_appointment_requests_business_id", "appointment_requests", ["business_id"]
    )
    op.create_index(
        "ix_appointment_requests_business_status",
        "appointment_requests",
        ["business_id", "status"],
    )
    op.create_index(
        "ix_appointment_requests_business_start",
        "appointment_requests",
        ["business_id", "scheduled_start_at"],
    )
    # Appointments becomes visible for existing tenants after the schema exists.
    op.execute(
        sa.text(
            """
            INSERT INTO business_modules (business_id, module_key, enabled, created_at, updated_at)
            SELECT b.id, 'appointments', true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM businesses b
            WHERE NOT EXISTS (
                SELECT 1 FROM business_modules bm
                WHERE bm.business_id = b.id AND bm.module_key = 'appointments'
            )
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM business_modules WHERE module_key = 'appointments'"))
    op.drop_index("ix_appointment_requests_business_start", table_name="appointment_requests")
    op.drop_index("ix_appointment_requests_business_status", table_name="appointment_requests")
    op.drop_index("ix_appointment_requests_business_id", table_name="appointment_requests")
    op.drop_table("appointment_requests")
