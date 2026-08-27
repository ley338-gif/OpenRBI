"""add node capacity breakdown fields

Revision ID: e3b3b0f8f6bd
Revises: 08940fd208c3
Create Date: 2026-08-27 17:25:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e3b3b0f8f6bd"
down_revision: Union[str, None] = "08940fd208c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("browser_nodes", sa.Column("capacity_bound", sa.String(length=16), nullable=True))
    op.add_column("browser_nodes", sa.Column("ram_capacity", sa.Integer(), nullable=True))
    op.add_column("browser_nodes", sa.Column("cpu_capacity", sa.Integer(), nullable=True))
    op.add_column("worker_metric_samples", sa.Column("capacity_bound", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("worker_metric_samples", "capacity_bound")
    op.drop_column("browser_nodes", "cpu_capacity")
    op.drop_column("browser_nodes", "ram_capacity")
    op.drop_column("browser_nodes", "capacity_bound")
