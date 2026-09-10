"""add platform roles

Revision ID: e1a4c7b2f001
Revises: d4e9f1a7c2b0
Create Date: 2026-09-08

Introduces a three-value platform role. ``is_platform_admin`` is deliberately
kept and kept in sync: dropping a column that live code still reads is a
separate, later decision.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1a4c7b2f001"
down_revision: Union[str, None] = "d4e9f1a7c2b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "platform_users",
        sa.Column("platform_role", sa.String(length=16), nullable=False, server_default="none"),
    )
    # Backfill from the existing boolean so no one loses access on deploy.
    op.execute("UPDATE platform_users SET platform_role = 'admin' WHERE is_platform_admin = TRUE")
    op.create_index("ix_platform_users_platform_role", "platform_users", ["platform_role"])


def downgrade() -> None:
    # is_platform_admin was never dropped, so no access is lost on the way down.
    op.drop_index("ix_platform_users_platform_role", table_name="platform_users")
    with op.batch_alter_table("platform_users") as batch_op:
        batch_op.drop_column("platform_role")
