"""add worker_metric_samples table

Revision ID: c72f8e1a94d5
Revises: b91a2d47e6c3
Create Date: 2026-08-13 15:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'c72f8e1a94d5'
down_revision: Union[str, None] = 'b91a2d47e6c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Roadmap Phase B / B1.10.2 — small internal metrics-history table backing
# the dashboard's Active Sessions graph and (later) per-worker graphs.
# Pruned to 7 days at insert time (app/services/metrics_history.py) — not
# a general-purpose time-series store.


def upgrade() -> None:
    op.create_table(
        'worker_metric_samples',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('node_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('cpu_percent', sa.Float(), nullable=True),
        sa.Column('ram_used_mb', sa.Integer(), nullable=True),
        sa.Column('ram_total_mb', sa.Integer(), nullable=True),
        sa.Column('active_sessions', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['node_id'], ['browser_nodes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_worker_metric_samples_node_id', 'worker_metric_samples', ['node_id'])
    op.create_index('ix_worker_metric_samples_recorded_at', 'worker_metric_samples', ['recorded_at'])


def downgrade() -> None:
    op.drop_index('ix_worker_metric_samples_recorded_at', table_name='worker_metric_samples')
    op.drop_index('ix_worker_metric_samples_node_id', table_name='worker_metric_samples')
    op.drop_table('worker_metric_samples')
