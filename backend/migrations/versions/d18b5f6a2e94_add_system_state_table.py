"""add system_state table

Revision ID: d18b5f6a2e94
Revises: a4c7e91f3b62
Create Date: 2026-08-13 12:05:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'd18b5f6a2e94'
down_revision: Union[str, None] = 'a4c7e91f3b62'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Roadmap Phase B / B1.9 — persisted, durable first-run-bootstrap state
# (app/models/system_state.py). Single-row table, same pattern as
# ldap_configs: a fixed primary key rather than COUNT(users) == 0, so
# deleting every user can never reopen the public bootstrap endpoints.


def upgrade() -> None:
    op.create_table(
        'system_state',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('initialized', sa.Boolean(), nullable=False),
        sa.Column('initialized_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('setup_admin_user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('setup_token_hash', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['setup_admin_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('system_state')
