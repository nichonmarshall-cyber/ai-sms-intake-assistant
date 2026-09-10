"""add multi-tenant platform foundation

Revision ID: d4e9f1a7c2b0
Revises: b830f1be6d5c
Create Date: 2026-09-03

The existing live demo is backfilled into one ``legacy-demo`` tenant.  The
application will switch to dynamic inbound-number routing in the next change;
this migration deliberately preserves every existing lead and call event.
"""

from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e9f1a7c2b0"
down_revision: Union[str, None] = "b830f1be6d5c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGACY_BUSINESS_ID = "legacy-demo"
LEGACY_DEMO_SETTINGS = {
    "intake": {
        "selection_mode": "menu",
        "demo_disclaimer": True,
        "enabled_profiles": [
            "auto_repair",
            "roofing",
            "painting",
            "lawn_care",
            "catering",
        ],
    },
    "missed_calls": {"enabled": False},
}


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

    with op.batch_alter_table("leads") as batch_op:
        batch_op.add_column(
            sa.Column("workflow_status", sa.String(length=32), nullable=False, server_default="new")
        )
        batch_op.add_column(sa.Column("client_notes", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("archived_by_user_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_leads_archived_by_user_id",
            "platform_users",
            ["archived_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("missed_call_events") as batch_op:
        batch_op.add_column(sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("archived_by_user_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_missed_call_events_archived_by_user_id",
            "platform_users",
            ["archived_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )

    if op.get_context().dialect.name == "postgresql":
        # PostgreSQL's static form keeps `alembic upgrade --sql` renderable;
        # SQLAlchemy cannot literalize a Python dictionary as JSON offline.
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
    else:
        businesses = sa.table(
            "businesses",
            sa.column("id", sa.String(length=36)),
            sa.column("name", sa.String(length=160)),
            sa.column("slug", sa.String(length=96)),
            sa.column("status", sa.String(length=24)),
            sa.column("default_profile_key", sa.String(length=32)),
            sa.column("settings", sa.JSON()),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        )
        now = datetime.now(timezone.utc)
        op.bulk_insert(
            businesses,
            [
                {
                    "id": LEGACY_BUSINESS_ID,
                    "name": "NTX Automation Co. Demo",
                    "slug": "ntx-demo",
                    "status": "active",
                    "default_profile_key": None,
                    "settings": LEGACY_DEMO_SETTINGS,
                    "created_at": now,
                    "updated_at": now,
                }
            ],
        )

    # Keep columns nullable in this migration so it can safely apply to a live
    # deployment before the runtime routing cutover. The next migration makes
    # them required after new code writes business_id on every record.
    for table in ("conversation_sessions", "leads", "processed_messages", "missed_call_events"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(sa.Column("business_id", sa.String(length=36), nullable=True))
            batch_op.create_foreign_key(
                f"fk_{table}_business_id",
                "businesses",
                ["business_id"],
                ["id"],
                ondelete="RESTRICT",
            )
            if table == "conversation_sessions":
                batch_op.drop_constraint("uq_conversation_sessions_phone", type_="unique")
                batch_op.create_unique_constraint(
                    "uq_conversation_sessions_business_phone", ["business_id", "phone"]
                )
        op.create_index(f"ix_{table}_business_id", table, ["business_id"])
        op.execute(sa.text(f"UPDATE {table} SET business_id = :business_id WHERE business_id IS NULL").bindparams(
            business_id=LEGACY_BUSINESS_ID
        ))


def downgrade() -> None:
    for table in ("missed_call_events", "processed_messages", "leads", "conversation_sessions"):
        op.drop_index(f"ix_{table}_business_id", table_name=table)
        with op.batch_alter_table(table) as batch_op:
            if table == "conversation_sessions":
                batch_op.drop_constraint(
                    "uq_conversation_sessions_business_phone", type_="unique"
                )
                batch_op.create_unique_constraint("uq_conversation_sessions_phone", ["phone"])
            batch_op.drop_constraint(f"fk_{table}_business_id", type_="foreignkey")
            batch_op.drop_column("business_id")

    with op.batch_alter_table("missed_call_events") as batch_op:
        batch_op.drop_constraint("fk_missed_call_events_archived_by_user_id", type_="foreignkey")
        batch_op.drop_column("archived_by_user_id")
        batch_op.drop_column("archived_at")

    with op.batch_alter_table("leads") as batch_op:
        batch_op.drop_constraint("fk_leads_archived_by_user_id", type_="foreignkey")
        batch_op.drop_column("archived_by_user_id")
        batch_op.drop_column("archived_at")
        batch_op.drop_column("client_notes")
        batch_op.drop_column("workflow_status")

    op.drop_index("ix_audit_events_business_created", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_business_memberships_user_id", table_name="business_memberships")
    op.drop_index("ix_business_memberships_business_id", table_name="business_memberships")
    op.drop_table("business_memberships")
    op.drop_index("ix_business_phone_numbers_business_id", table_name="business_phone_numbers")
    op.drop_table("business_phone_numbers")
    op.drop_table("platform_users")
    op.drop_table("businesses")
