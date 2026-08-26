"""Add node enrollment fields and security events (Roadmap B2.1).

Revision ID: 08940fd208c3
Revises: 112d0613aefc
Create Date: 2026-08-26 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "08940fd208c3"
down_revision: str | None = "112d0613aefc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NODE_ENROLLMENT_STATUS = postgresql.ENUM("PENDING", "APPROVED", "REVOKED", name="node_enrollment_status")


def upgrade() -> None:
    _NODE_ENROLLMENT_STATUS.create(op.get_bind(), checkfirst=True)
    # server_default="APPROVED": every existing row was created through
    # the trusted, operator-configured single-node auto-registration path
    # (refresh_node_from_agent()), which predates this concept entirely —
    # see docs/adr/0023-node-enrollment-and-trust-model.md's Consequences.
    # Only enroll_node() (the new token-gated path) ever inserts PENDING.
    op.add_column(
        "browser_nodes",
        sa.Column("enrollment_status", _NODE_ENROLLMENT_STATUS, server_default="APPROVED", nullable=False),
    )
    op.add_column("browser_nodes", sa.Column("endpoint_url", sa.String(length=512), nullable=True))
    op.add_column("browser_nodes", sa.Column("agent_token_encrypted", sa.LargeBinary(), nullable=True))

    op.execute("ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS 'NODE_ENROLLMENT_REQUESTED'")
    op.execute("ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS 'NODE_APPROVED'")
    op.execute("ALTER TYPE security_event_type ADD VALUE IF NOT EXISTS 'NODE_REVOKED'")


def downgrade() -> None:
    op.drop_column("browser_nodes", "agent_token_encrypted")
    op.drop_column("browser_nodes", "endpoint_url")
    op.drop_column("browser_nodes", "enrollment_status")
    _NODE_ENROLLMENT_STATUS.drop(op.get_bind(), checkfirst=True)
    # PostgreSQL enum values cannot be dropped without rebuilding the type.
