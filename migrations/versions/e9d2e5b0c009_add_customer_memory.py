"""add customer memory and proposal tables

Revision ID: e9d2e5b0c009
Revises: e8c1d4a9b008
"""

from alembic import op
import sqlalchemy as sa

revision = "e9d2e5b0c009"
down_revision = "e8c1d4a9b008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "customer_memories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("business_id", sa.String(36), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("customer_name", sa.String(160), nullable=True),
        sa.Column("rolling_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("summary_source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("business_id", "phone", name="uq_customer_memories_business_phone"),
    )
    op.create_index("ix_customer_memories_business_id", "customer_memories", ["business_id"])
    op.create_index("ix_customer_memories_business_updated", "customer_memories", ["business_id", "updated_at"])
    op.create_table(
        "customer_memory_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("business_id", sa.String(36), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_memory_id", sa.Integer(), sa.ForeignKey("customer_memories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("record_type", sa.String(48), nullable=False),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(48), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_customer_memory_records_business_id", "customer_memory_records", ["business_id"])
    op.create_index("ix_customer_memory_records_customer_memory_id", "customer_memory_records", ["customer_memory_id"])
    op.create_index("ix_customer_memory_records_customer_type", "customer_memory_records", ["customer_memory_id", "record_type"])
    op.create_table(
        "memory_update_proposals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("business_id", sa.String(36), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_memory_id", sa.Integer(), sa.ForeignKey("customer_memories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("record_id", sa.Integer(), sa.ForeignKey("customer_memory_records.id", ondelete="CASCADE"), nullable=True),
        sa.Column("record_type", sa.String(48), nullable=False),
        sa.Column("proposed_values", sa.JSON(), nullable=False),
        sa.Column("proposed_status", sa.String(48), nullable=True),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("source_session_id", sa.Integer(), sa.ForeignKey("conversation_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("resolved_by_user_id", sa.String(36), sa.ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_memory_update_proposals_business_id", "memory_update_proposals", ["business_id"])
    op.create_index("ix_memory_update_proposals_customer_memory_id", "memory_update_proposals", ["customer_memory_id"])
    op.create_index("ix_memory_proposals_business_status", "memory_update_proposals", ["business_id", "status"])


def downgrade():
    op.drop_table("memory_update_proposals")
    op.drop_table("customer_memory_records")
    op.drop_table("customer_memories")
