"""add QUARANTINE_FILE_RETENTION_EXPIRED security event

Revision ID: c48e6a1f9d73
Revises: a91c4e6b7d3f
Create Date: 2026-08-14 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'c48e6a1f9d73'
down_revision: Union[str, None] = 'a91c4e6b7d3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Downloads/quarantine retention (app/core/quarantine_retention.py).
#
# NOTE: authored in parallel with another migration (a7c39f2e5d81, "add
# ORPHAN_SESSION_RECONCILED security event") off the same parent revision
# a91c4e6b7d3f, as two independent PRs. Whichever of the two merges
# second will need a small follow-up migration to merge the resulting
# branch heads (`alembic merge heads`) — expected and harmless, not a
# sign either migration is wrong.


def upgrade() -> None:
    op.execute("ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS 'QUARANTINE_FILE_RETENTION_EXPIRED'")


def downgrade() -> None:
    # Postgres enums cannot have values dropped — see every prior migration
    # in this series for the same, already-established note.
    pass
