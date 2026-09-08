"""add auth sessions and login throttle

Revision ID: e2b5d8c3f002
Revises: e1a4c7b2f001
Create Date: 2026-09-08

Server-side revocable sessions plus a database-backed login throttle. The
throttle lives in Postgres rather than process memory because Gunicorn runs
multiple workers and an in-memory counter would multiply the allowance.

Only hashes are stored: token_hash and csrf_hash are SHA-256 of high-entropy
tokens, and ip_hash is a keyed HMAC. No raw IP address is ever persisted.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2b5d8c3f002"
down_revision: Union[str, None] = "e1a4c7b2f001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["platform_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_user_sessions_token_hash"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_user_created", "user_sessions", ["user_id", "created_at"])
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"])

    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email_lower", sa.String(length=320), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_login_attempts_email_created", "login_attempts", ["email_lower", "created_at"])
    op.create_index("ix_login_attempts_ip_created", "login_attempts", ["ip_hash", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_login_attempts_ip_created", table_name="login_attempts")
    op.drop_index("ix_login_attempts_email_created", table_name="login_attempts")
    op.drop_table("login_attempts")

    op.drop_index("ix_user_sessions_expires_at", table_name="user_sessions")
    op.drop_index("ix_user_sessions_user_created", table_name="user_sessions")
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")
