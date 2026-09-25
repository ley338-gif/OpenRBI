"""add system_state.seeded_policy_templates

Revision ID: 3c6f0e8b2a57
Revises: 8e4d2a6c9f13
Create Date: 2026-09-25 19:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3c6f0e8b2a57"
down_revision: Union[str, None] = "8e4d2a6c9f13"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "system_state",
        sa.Column(
            "seeded_policy_templates",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("system_state", "seeded_policy_templates")
