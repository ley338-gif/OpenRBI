"""add worker metric sample capacity

Revision ID: 5b2e9c7a1d40
Revises: c4a9e1d7f2b3
Create Date: 2026-09-25 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "5b2e9c7a1d40"
down_revision: Union[str, None] = "c4a9e1d7f2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable: samples recorded before this migration simply don't count
    # toward the "no free slots" warning window (dashboard.py).
    op.add_column("worker_metric_samples", sa.Column("capacity", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("worker_metric_samples", "capacity")
