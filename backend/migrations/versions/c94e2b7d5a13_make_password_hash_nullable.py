"""make users.password_hash nullable for LDAP-only accounts

Revision ID: c94e2b7d5a13
Revises: b3d8f1a29c47
Create Date: 2026-08-13 09:05:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c94e2b7d5a13'
down_revision: Union[str, None] = 'b3d8f1a29c47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Roadmap Phase B / B1.3, docs/adr/0015 — a just-in-time-provisioned LDAP
# user has no local password to store (LDAP credentials are never cached
# locally). NULL here means "this account is LDAP-only, authenticate via
# LDAP" — LocalAuthProvider explicitly rejects a NULL hash rather than
# attempting to verify against one, so this can never be misread as "no
# password required."


def upgrade() -> None:
    op.alter_column('users', 'password_hash', existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    # Not reversible in general — any row with a NULL password_hash by
    # this point (a real LDAP-provisioned account) has no value to fill
    # in; a real rollback would need an operator decision (delete those
    # rows, or assign them a real local password) rather than a script
    # silently picking one for them.
    pass
