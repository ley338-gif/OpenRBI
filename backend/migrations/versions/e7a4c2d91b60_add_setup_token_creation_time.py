"""add setup token creation time

Revision ID: e7a4c2d91b60
Revises: d5e8a13c6f92
Create Date: 2026-08-15 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7a4c2d91b60"
down_revision: Union[str, None] = "d5e8a13c6f92"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "system_state",
        sa.Column("setup_token_created_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("system_state", "setup_token_created_at")
