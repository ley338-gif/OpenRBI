"""add USER_PROVISIONED_VIA_LDAP security event type

Revision ID: b3d8f1a29c47
Revises: a1c2e4f6b8d0
Create Date: 2026-08-13 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'b3d8f1a29c47'
down_revision: Union[str, None] = 'a1c2e4f6b8d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Roadmap Phase B / B1.3 — a successful LDAP login for a username with no
# existing local account creates one (just-in-time provisioning, exact
# username match only, no local password ever stored — docs/adr/0015).
# That's a real account-creation event distinct from an admin-issued
# USER_CREATED and must be independently auditable.
NEW_VALUE = "USER_PROVISIONED_VIA_LDAP"


def upgrade() -> None:
    op.execute(f"ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS '{NEW_VALUE}'")


def downgrade() -> None:
    # PostgreSQL has no DROP VALUE for enums; not implemented — see
    # fb0465bc5376's downgrade for the same rationale.
    pass
