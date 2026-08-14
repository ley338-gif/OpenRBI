"""add CLIPBOARD_ACCESS_BLOCKED security event

Revision ID: c2a5e8f13b96
Revises: b18d4f6e0a72
Create Date: 2026-08-14 21:31:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'c2a5e8f13b96'
down_revision: Union[str, None] = 'b18d4f6e0a72'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Real clipboard-policy enforcement (app/core/rfb_clipboard_filter.py).


def upgrade() -> None:
    op.execute("ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS 'CLIPBOARD_ACCESS_BLOCKED'")


def downgrade() -> None:
    # Postgres enums cannot have values dropped — see every prior migration
    # in this series for the same, already-established note.
    pass
