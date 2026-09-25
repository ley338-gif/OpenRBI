"""add policy archived_at

Revision ID: 8e4d2a6c9f13
Revises: 5b2e9c7a1d40
Create Date: 2026-09-25 10:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "8e4d2a6c9f13"
down_revision: Union[str, None] = "5b2e9c7a1d40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("policies", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("policies", "archived_at")
