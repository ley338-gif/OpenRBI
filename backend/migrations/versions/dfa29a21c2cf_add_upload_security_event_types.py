"""add upload security event types

Revision ID: dfa29a21c2cf
Revises: fb0465bc5376
Create Date: 2026-08-12 10:56:34.540130

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'dfa29a21c2cf'
down_revision: Union[str, None] = 'fb0465bc5376'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Extensions beyond the project brief's minimum event list (see
# app/models/enums.py:SecurityEventType) — the upload pipeline (Phase 16)
# needs its own events, mirroring DOWNLOAD_REQUESTED/DOWNLOAD_BLOCKED.
NEW_VALUES = (
    "UPLOAD_REQUESTED",
    "UPLOAD_BLOCKED",
)


def upgrade() -> None:
    for value in NEW_VALUES:
        op.execute(f"ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # PostgreSQL has no DROP VALUE for enums; removing one requires
    # rebuilding the type. Not implemented — see the identical note in
    # fb0465bc5376_add_admin_management_security_event_.py.
    pass
