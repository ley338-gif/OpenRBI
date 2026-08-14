"""add ORPHAN_SESSION_RECONCILED security event

Revision ID: a7c39f2e5d81
Revises: a91c4e6b7d3f
Create Date: 2026-08-14 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a7c39f2e5d81'
down_revision: Union[str, None] = 'a91c4e6b7d3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Orphan-container reconciliation (app/core/orphan_reconciler.py).


def upgrade() -> None:
    op.execute("ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS 'ORPHAN_SESSION_RECONCILED'")


def downgrade() -> None:
    # Postgres enums cannot have values dropped — see every prior migration
    # in this series for the same, already-established note.
    pass
