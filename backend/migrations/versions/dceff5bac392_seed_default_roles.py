"""seed default roles

Revision ID: dceff5bac392
Revises: ada766b187c5
Create Date: 2026-08-12 08:13:06.141872

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = 'dceff5bac392'
down_revision: Union[str, None] = 'ada766b187c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Fixed MVP 1 role set (see docs/security-model.md / the project's role
# definitions). Roles are a small closed set for MVP 1, so they're seeded by
# migration rather than requiring an admin bootstrap step.
ROLES = [
    ("USER", "Can start/end their own browser sessions, manage their own MFA, and retrieve their own released downloads."),
    ("SECURITY_REVIEWER", "Can view and isolate sessions, manage incidents, and review (release/reject) quarantined files."),
    ("ADMIN", "Full user, group, policy, and system administration, plus all SECURITY_REVIEWER capabilities."),
]

roles_table = sa.table(
    "roles",
    sa.column("id", UUID(as_uuid=True)),
    sa.column("name", sa.String),
    sa.column("description", sa.String),
)


def upgrade() -> None:
    op.bulk_insert(
        roles_table,
        [{"id": uuid.uuid4(), "name": name, "description": description} for name, description in ROLES],
    )


def downgrade() -> None:
    op.execute(roles_table.delete().where(roles_table.c.name.in_([name for name, _ in ROLES])))
