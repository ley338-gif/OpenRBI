"""add ACCOUNT_LOCKED/ACCOUNT_UNLOCKED security events

Revision ID: d3f8a52c917e
Revises: a4e7c19b6f52
Create Date: 2026-08-13 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'd3f8a52c917e'
down_revision: Union[str, None] = 'a4e7c19b6f52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Roadmap Phase B / B1.10.5 — admin Account Lock/Unlock.


def upgrade() -> None:
    op.execute("ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS 'ACCOUNT_LOCKED'")
    op.execute("ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS 'ACCOUNT_UNLOCKED'")


def downgrade() -> None:
    # Postgres enums cannot have values dropped — see every prior migration
    # in this series for the same, already-established note.
    pass
