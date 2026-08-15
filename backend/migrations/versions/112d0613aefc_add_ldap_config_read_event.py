"""add LDAP_CONFIG_READ security event

Revision ID: 112d0613aefc
Revises: a8d1f6c42e90
Create Date: 2026-08-15 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "112d0613aefc"
down_revision: Union[str, None] = "a8d1f6c42e90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS 'LDAP_CONFIG_READ'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be dropped without rebuilding the type.
    pass
