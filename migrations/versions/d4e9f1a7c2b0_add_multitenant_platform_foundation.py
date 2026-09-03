"""add multi-tenant platform foundation

Revision ID: d4e9f1a7c2b0
Revises: b830f1be6d5c
Create Date: 2026-09-03

The existing live demo is backfilled into one ``legacy-demo`` tenant.  The
application will switch to dynamic inbound-number routing in the next change;
this migration deliberately preserves every existing lead and call event.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e9f1a7c2b0"
down_revision: Union[str, None] = "b830f1be6d5c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGACY_BUSINESS_ID = "legacy-demo"


def upgrade() -> None:
    op.create_table(
        "businesses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("slug", sa.String(length=96), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("default_profile_key", sa.String(length=32), nullable=True),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "platform_users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_platform_admin", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "business_phone_numbers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phone", name="uq_business_phone_numbers_phone"),
    )
    op.create_index("ix_business_phone_numbers_business_id", "business_phone_numbers", ["business_id"])
    op.create_table(
        "business_memberships",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["platform_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "user_id", name="uq_business_membership"),
    )
    op.create_index("ix_business_memberships_business_id", "business_memberships", ["business_id"])
    op.create_index("ix_business_memberships_user_id", "business_memberships", ["user_id"])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=True),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=96), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["platform_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_business_created", "audit_events", ["business_id", "created_at"])

    op.add_column(
        "leads", sa.Column("workflow_status", sa.String(length=32), nullable=False, server_default="new")
    )
    op.add_column("leads", sa.Column("client_notes", sa.Text(), nullable=True))
    op.add_column("leads", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("leads", sa.Column("archived_by_user_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_leads_archived_by_user_id",
        "leads",
        "platform_users",
        ["archived_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("missed_call_events", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "missed_call_events", sa.Column("archived_by_user_id", sa.String(length=36), nullable=True)
    )
    op.create_foreign_key(
        "fk_missed_call_events_archived_by_user_id",
        "missed_call_events",
        "platform_users",
        ["archived_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Static PostgreSQL SQL is intentional: Alembic cannot render a Python dict
    # as a JSON literal during `alembic upgrade --sql`. json_build_object also
    # avoids SQLAlchemy interpreting JSON colon tokens as bind parameters.
    op.execute(
        """
        INSERT INTO businesses
            (id, name, slug, status, default_profile_key, settings, created_at, updated_at)
        VALUES
            (
                'legacy-demo',
                'NTX Automation Co. Demo',
                'ntx-demo',
                'active',
                NULL,
                json_build_object(
                    'intake', json_build_object(
                        'selection_mode', 'menu',
                        'demo_disclaimer', TRUE,
                        'enabled_profiles', json_build_array(
                            'auto_repair', 'roofing', 'painting', 'lawn_care', 'catering'
                        )
                    ),
                    'missed_calls', json_build_object('enabled', FALSE)
                ),
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
        """
    )

    # Keep columns nullable in this migration so it can safely apply to a live
    # deployment before the runtime routing cutover. The next migration makes
    # them required after new code writes business_id on every record.
    for table in ("conversation_sessions", "leads", "processed_messages", "missed_call_events"):
        op.add_column(table, sa.Column("business_id", sa.String(length=36), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_business_id", table, "businesses", ["business_id"], ["id"], ondelete="RESTRICT"
        )
        op.create_index(f"ix_{table}_business_id", table, ["business_id"])
        op.execute(sa.text(f"UPDATE {table} SET business_id = :business_id WHERE business_id IS NULL").bindparams(
            business_id=LEGACY_BUSINESS_ID
        ))

    op.drop_constraint("uq_conversation_sessions_phone", "conversation_sessions", type_="unique")
    op.create_unique_constraint(
        "uq_conversation_sessions_business_phone", "conversation_sessions", ["business_id", "phone"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_conversation_sessions_business_phone", "conversation_sessions", type_="unique")
    op.create_unique_constraint("uq_conversation_sessions_phone", "conversation_sessions", ["phone"])

    for table in ("missed_call_events", "processed_messages", "leads", "conversation_sessions"):
        op.drop_index(f"ix_{table}_business_id", table_name=table)
        op.drop_constraint(f"fk_{table}_business_id", table, type_="foreignkey")
        op.drop_column(table, "business_id")

    op.drop_constraint(
        "fk_missed_call_events_archived_by_user_id", "missed_call_events", type_="foreignkey"
    )
    op.drop_column("missed_call_events", "archived_by_user_id")
    op.drop_column("missed_call_events", "archived_at")
    op.drop_constraint("fk_leads_archived_by_user_id", "leads", type_="foreignkey")
    op.drop_column("leads", "archived_by_user_id")
    op.drop_column("leads", "archived_at")
    op.drop_column("leads", "client_notes")
    op.drop_column("leads", "workflow_status")

    op.drop_index("ix_audit_events_business_created", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_business_memberships_user_id", table_name="business_memberships")
    op.drop_index("ix_business_memberships_business_id", table_name="business_memberships")
    op.drop_table("business_memberships")
    op.drop_index("ix_business_phone_numbers_business_id", table_name="business_phone_numbers")
    op.drop_table("business_phone_numbers")
    op.drop_table("platform_users")
    op.drop_table("businesses")
