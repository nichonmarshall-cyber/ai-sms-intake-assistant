"""harden missed call delivery

Revision ID: e4d7f0a5f004
Revises: e3c6e9d4f003
Create Date: 2026-09-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4d7f0a5f004"
down_revision: Union[str, None] = "e3c6e9d4f003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("missed_call_events") as batch_op:
        batch_op.add_column(sa.Column("call_status", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("call_duration_seconds", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("delivery_status", sa.String(length=32), nullable=True))
        batch_op.add_column(
            sa.Column("send_attempts", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("error_code", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("missed_call_events") as batch_op:
        batch_op.drop_column("error_code")
        batch_op.drop_column("last_attempt_at")
        batch_op.drop_column("send_attempts")
        batch_op.drop_column("delivery_status")
        batch_op.drop_column("call_duration_seconds")
        batch_op.drop_column("call_status")
