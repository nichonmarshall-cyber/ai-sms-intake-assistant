"""add business module entitlements

Revision ID: e3c6e9d4f003
Revises: e2b5d8c3f002
Create Date: 2026-09-08

Absence of a row means "not entitled". Existing businesses are seeded with the
modules that Phases 1a and 2 actually cover, so nothing is silently turned on
for a client before it exists.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3c6e9d4f003"
down_revision: Union[str, None] = "e2b5d8c3f002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_MODULES = ("overview", "leads", "conversations", "ai_intake", "settings")


def upgrade() -> None:
    op.create_table(
        "business_modules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("module_key", sa.String(length=48), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "module_key", name="uq_business_modules_business_key"),
    )
    op.create_index("ix_business_modules_business_id", "business_modules", ["business_id"])

    for module_key in DEFAULT_MODULES:
        op.execute(
            sa.text(
                """
                INSERT INTO business_modules
                    (business_id, module_key, enabled, created_at, updated_at)
                SELECT id, :module_key, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                FROM businesses
                """
            ).bindparams(module_key=module_key)
        )


def downgrade() -> None:
    op.drop_index("ix_business_modules_business_id", table_name="business_modules")
    op.drop_table("business_modules")
