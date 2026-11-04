"""add module configurations

Revision ID: e8c1d4a9b008
Revises: e7b0c3d8a007
Create Date: 2026-11-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8c1d4a9b008"
down_revision: Union[str, None] = "e7b0c3d8a007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "appointment_requests",
        sa.Column("approval_message_sid", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "appointment_requests",
        sa.Column("approval_message_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "appointment_requests",
        sa.Column("approval_message_error", sa.String(length=255), nullable=True),
    )
    op.create_table(
        "business_module_configurations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("module_key", sa.String(length=48), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id", "module_key", name="uq_business_module_configurations_business_key"
        ),
    )
    op.create_index(
        "ix_business_module_configurations_business_id",
        "business_module_configurations",
        ["business_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_business_module_configurations_business_id",
        table_name="business_module_configurations",
    )
    op.drop_table("business_module_configurations")
    op.drop_column("appointment_requests", "approval_message_error")
    op.drop_column("appointment_requests", "approval_message_sent_at")
    op.drop_column("appointment_requests", "approval_message_sid")
