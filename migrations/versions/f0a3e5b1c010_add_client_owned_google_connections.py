"""add client owned Google connections

Revision ID: f0a3e5b1c010
Revises: e9d2e5b0c009
"""

from alembic import op
import sqlalchemy as sa

revision = "f0a3e5b1c010"
down_revision = "e9d2e5b0c009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "google_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("business_id", sa.String(36), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connected_by_user_id", sa.String(36), sa.ForeignKey("platform_users.id", ondelete="SET NULL")),
        sa.Column("connected_email", sa.String(320)),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=False),
        sa.Column("granted_scopes", sa.JSON(), nullable=False),
        sa.Column("search_property", sa.String(512)),
        sa.Column("ga4_property", sa.String(96)),
        sa.Column("ga4_measurement_id", sa.String(32)),
        sa.Column("profile_location", sa.String(128)),
        sa.Column("profile_url", sa.String(2048)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("business_id", name="uq_google_connections_business"),
    )
    op.create_index("ix_google_connections_business_id", "google_connections", ["business_id"])
    op.create_table(
        "google_oauth_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column("business_id", sa.String(36), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("platform_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("state_hash", name="uq_google_oauth_states_hash"),
    )
    op.create_index("ix_google_oauth_states_business_id", "google_oauth_states", ["business_id"])
    op.create_index("ix_google_oauth_states_expires", "google_oauth_states", ["expires_at"])


def downgrade():
    op.drop_table("google_oauth_states")
    op.drop_table("google_connections")
