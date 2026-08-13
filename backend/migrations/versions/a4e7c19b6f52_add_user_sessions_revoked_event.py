"""add USER_SESSIONS_REVOKED security event

Revision ID: a4e7c19b6f52
Revises: c72f8e1a94d5
Create Date: 2026-08-13 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a4e7c19b6f52'
down_revision: Union[str, None] = 'c72f8e1a94d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Roadmap Phase B / B1.10.4 — bulk session revocation from the User Detail page.


def upgrade() -> None:
    op.execute("ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS 'USER_SESSIONS_REVOKED'")


def downgrade() -> None:
    # Postgres enums cannot have values dropped — see every prior migration
    # in this series for the same, already-established note.
    pass
