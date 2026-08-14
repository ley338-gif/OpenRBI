"""add SESSION_LOST_RECONCILED security event

Revision ID: d5e8a13c6f92
Revises: c2a5e8f13b96
Create Date: 2026-08-15 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'd5e8a13c6f92'
down_revision: Union[str, None] = 'c2a5e8f13b96'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Reverse direction of orphan-container reconciliation
# (app/core/orphan_reconciler.py) — a BrowserSession row that should have a
# running container but doesn't.


def upgrade() -> None:
    op.execute("ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS 'SESSION_LOST_RECONCILED'")


def downgrade() -> None:
    # Postgres enums cannot have values dropped — see every prior migration
    # in this series for the same, already-established note.
    pass
