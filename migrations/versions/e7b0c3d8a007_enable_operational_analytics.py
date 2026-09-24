"""enable operational analytics

Revision ID: e7b0c3d8a007
Revises: e6a9b2c7d006
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7b0c3d8a007"
down_revision: Union[str, None] = "e6a9b2c7d006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO business_modules (business_id, module_key, enabled, created_at, updated_at)
            SELECT id, 'analytics', TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM businesses b
            WHERE NOT EXISTS (
                SELECT 1 FROM business_modules bm
                WHERE bm.business_id = b.id AND bm.module_key = 'analytics'
            )
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM business_modules WHERE module_key = 'analytics'"))
