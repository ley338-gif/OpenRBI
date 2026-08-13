"""add LDAP admin-config security event types

Revision ID: e15f9a4b2c68
Revises: c94e2b7d5a13
Create Date: 2026-08-13 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'e15f9a4b2c68'
down_revision: Union[str, None] = 'c94e2b7d5a13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Roadmap Phase B / B1.8 — LDAP is now configurable through the admin
# portal; these must be independently auditable the same way policy
# publish/change already are.
NEW_VALUES = ["LDAP_CONFIG_CHANGED", "LDAP_ENABLED", "LDAP_DISABLED", "LDAP_CONNECTION_TESTED"]


def upgrade() -> None:
    for value in NEW_VALUES:
        op.execute(f"ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # PostgreSQL has no DROP VALUE for enums; not implemented — see
    # fb0465bc5376's downgrade for the same rationale.
    pass
