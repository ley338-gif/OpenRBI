"""add SESSION_START_FAILED security event

Revision ID: a8d1f6c42e90
Revises: e7a4c2d91b60
Create Date: 2026-08-15 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "a8d1f6c42e90"
down_revision: Union[str, None] = "e7a4c2d91b60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS 'SESSION_START_FAILED'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be dropped without rebuilding the type.
    pass
