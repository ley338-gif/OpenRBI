"""add ldap_configs table

Revision ID: f27a6e93d158
Revises: e15f9a4b2c68
Create Date: 2026-08-13 10:05:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'f27a6e93d158'
down_revision: Union[str, None] = 'e15f9a4b2c68'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Roadmap Phase B / B1.8 — persisted, admin-portal-editable LDAP
# configuration (app/models/ldap_config.py). Single-row table: no row at
# all means "fall back to the pre-existing OPENRBI_LDAP_* env vars"
# (app/services/ldap_config_service.py); once a row exists, it is
# authoritative, env vars are no longer consulted.


def upgrade() -> None:
    op.create_table(
        'ldap_configs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('server_uri', sa.String(length=512), nullable=False),
        sa.Column('use_starttls', sa.Boolean(), nullable=False),
        sa.Column('bind_dn', sa.String(length=512), nullable=False),
        sa.Column('bind_password_encrypted', sa.LargeBinary(), nullable=True),
        sa.Column('base_dn', sa.String(length=512), nullable=False),
        sa.Column('user_search_filter', sa.String(length=512), nullable=False),
        sa.Column('group_attribute', sa.String(length=255), nullable=False),
        sa.Column('group_role_mapping', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('ldap_configs')
