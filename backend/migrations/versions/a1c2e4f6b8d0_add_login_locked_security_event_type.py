"""add LOGIN_LOCKED security event type

Revision ID: a1c2e4f6b8d0
Revises: dfa29a21c2cf
Create Date: 2026-08-12 12:10:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a1c2e4f6b8d0'
down_revision: Union[str, None] = 'dfa29a21c2cf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Phase 20 hardening: a per-username login-attempt lockout on /auth/login
# (app/core/sessions.py:is_login_locked) needs its own auditable event,
# distinct from an individual USER_LOGIN_FAILED, so a reviewer can see when
# an account was actually locked out, not just that one attempt failed.
NEW_VALUE = "LOGIN_LOCKED"


def upgrade() -> None:
    op.execute(f"ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS '{NEW_VALUE}'")


def downgrade() -> None:
    # PostgreSQL has no DROP VALUE for enums; not implemented — see
    # fb0465bc5376's downgrade for the same rationale.
    pass
