"""Add browser_sessions screen resolution.

Revision ID: a91c4e6b7d3f
Revises: b740f0e26a1d
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a91c4e6b7d3f"
down_revision: str | None = "b740f0e26a1d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "browser_sessions",
        sa.Column("screen_width", sa.Integer(), server_default="1280", nullable=False),
    )
    op.add_column(
        "browser_sessions",
        sa.Column("screen_height", sa.Integer(), server_default="800", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("browser_sessions", "screen_height")
    op.drop_column("browser_sessions", "screen_width")
