"""add admin management security event types

Revision ID: fb0465bc5376
Revises: 24556c633c40
Create Date: 2026-08-12 08:37:55.319140

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'fb0465bc5376'
down_revision: Union[str, None] = '24556c633c40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Extensions beyond the project brief's minimum event list (see
# app/models/enums.py:SecurityEventType) for admin user/group management,
# which is security-relevant and must be auditable too.
NEW_VALUES = (
    "USER_ROLE_CHANGED",
    "USER_GROUPS_CHANGED",
    "PASSWORD_RESET_BY_ADMIN",
    "GROUP_CREATED",
    "GROUP_DELETED",
)


def upgrade() -> None:
    for value in NEW_VALUES:
        op.execute(f"ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # PostgreSQL has no DROP VALUE for enums; removing one requires
    # rebuilding the type (rename, create new, migrate column, drop old).
    # Not implemented — downgrading past this revision while any of these
    # values is in use in security_events is not supported.
    pass
