"""add browser_sessions.viewer_connected_at

Revision ID: 5d2e8a1c9f40
Revises: 3c6f0e8b2a57
Create Date: 2026-10-04 09:00:00.000000

Set while a viewer's display connection is open (app/api/display.py), so
app/core/session_reaper.py can tell an ACTIVE session somebody is looking at
from one nobody has connected to since it started or was restored.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "5d2e8a1c9f40"
down_revision: Union[str, None] = "3c6f0e8b2a57"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("browser_sessions", sa.Column("viewer_connected_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("browser_sessions", "viewer_connected_at")
