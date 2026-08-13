"""add worker telemetry columns, MAINTENANCE status, worker security events

Revision ID: b91a2d47e6c3
Revises: d18b5f6a2e94
Create Date: 2026-08-13 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b91a2d47e6c3'
down_revision: Union[str, None] = 'd18b5f6a2e94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Roadmap Phase B / B1.10.1 — worker telemetry + health model.


def upgrade() -> None:
    op.execute("ALTER TYPE browser_node_status ADD VALUE IF NOT EXISTS 'MAINTENANCE'")
    op.execute("ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS 'WORKER_DRAIN_ENABLED'")
    op.execute("ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS 'WORKER_DRAIN_DISABLED'")
    op.execute("ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS 'WORKER_MAINTENANCE_ENABLED'")
    op.execute("ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS 'WORKER_MAINTENANCE_DISABLED'")

    op.add_column('browser_nodes', sa.Column('cpu_percent', sa.Float(), nullable=True))
    op.add_column('browser_nodes', sa.Column('ram_total_mb', sa.Integer(), nullable=True))
    op.add_column('browser_nodes', sa.Column('ram_used_mb', sa.Integer(), nullable=True))
    op.add_column('browser_nodes', sa.Column('node_started_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('browser_nodes', 'node_started_at')
    op.drop_column('browser_nodes', 'ram_used_mb')
    op.drop_column('browser_nodes', 'ram_total_mb')
    op.drop_column('browser_nodes', 'cpu_percent')
    # Postgres enums cannot have values dropped — see every prior migration
    # in this series for the same, already-established note.
