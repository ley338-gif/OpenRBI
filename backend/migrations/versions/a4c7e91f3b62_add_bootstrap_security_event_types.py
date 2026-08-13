"""add bootstrap security event types

Revision ID: a4c7e91f3b62
Revises: f27a6e93d158
Create Date: 2026-08-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a4c7e91f3b62'
down_revision: Union[str, None] = 'f27a6e93d158'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Roadmap Phase B / B1.9 — first-run bootstrap admin creation.


def upgrade() -> None:
    op.execute("ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS 'INITIAL_ADMIN_CREATED'")
    op.execute("ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS 'SYSTEM_INITIALIZED'")


def downgrade() -> None:
    # Postgres cannot drop enum values — see every prior migration in this
    # series (e.g. e15f9a4b2c68) for the same, already-established note.
    pass
