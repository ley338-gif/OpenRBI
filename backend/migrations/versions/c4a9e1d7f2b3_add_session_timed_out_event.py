"""add SESSION_TIMED_OUT security event

Revision ID: c4a9e1d7f2b3
Revises: e3b3b0f8f6bd
Create Date: 2026-09-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "c4a9e1d7f2b3"
down_revision: Union[str, None] = "e3b3b0f8f6bd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS 'SESSION_TIMED_OUT'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be dropped without rebuilding the type.
    pass
