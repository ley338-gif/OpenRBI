"""Add browser_sessions clipboard_mode.

Revision ID: b18d4f6e0a72
Revises: 9cb7744440ec
Create Date: 2026-08-14 21:30:00.000000

NOTE: originally authored against a7c39f2e5d81 (the head at the time),
rebased onto 9cb7744440ec after that head was superseded by the
orphan-reconciliation/quarantine-retention merge migration landing on
main first — same situation c48e6a1f9d73's own note describes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b18d4f6e0a72"
down_revision: str | None = "9cb7744440ec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CLIPBOARD_MODE = postgresql.ENUM(
    "NONE", "LOCAL_TO_REMOTE", "REMOTE_TO_LOCAL", "BIDIRECTIONAL_TEXT", name="clipboard_mode"
)


def upgrade() -> None:
    _CLIPBOARD_MODE.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "browser_sessions",
        sa.Column(
            "clipboard_mode",
            _CLIPBOARD_MODE,
            server_default="BIDIRECTIONAL_TEXT",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("browser_sessions", "clipboard_mode")
    _CLIPBOARD_MODE.drop(op.get_bind(), checkfirst=True)
