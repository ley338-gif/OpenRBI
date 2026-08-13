"""Add policy updated timestamp.

Revision ID: b740f0e26a1d
Revises: d3f8a52c917e
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b740f0e26a1d"
down_revision: str | None = "d3f8a52c917e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "policies",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("policies", "updated_at")
