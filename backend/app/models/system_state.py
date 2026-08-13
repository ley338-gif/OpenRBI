import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Roadmap B1.9 — single-row table, same pattern as app/models/ldap_config.py's
# LDAP_CONFIG_ID: a fixed, well-known primary key is a structural guarantee
# of "at most one row that matters," reused here for "has this installation
# completed first-run setup" — a question with exactly one persistent
# answer for the whole installation, not per-user or per-request state.
SYSTEM_STATE_ID = uuid.UUID("00000000-0000-0000-0000-0000005e7057")


class SystemState(Base):
    """Persisted, durable record of whether this installation has completed
    first-run bootstrap (docs/adr/0017-first-run-bootstrap.md). Deliberately
    NOT derived from `COUNT(users) == 0` — that check would let deleting
    every user silently reopen the public, unauthenticated bootstrap
    endpoints, a privilege-escalation path. `initialized` only ever
    transitions false -> true, once, and is never reset by anything other
    than a direct operator database edit.
    """

    __tablename__ = "system_state"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=lambda: SYSTEM_STATE_ID)

    initialized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    initialized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # The one local User row a bootstrap POST /setup/admin call creates or
    # reuses on retry (before MFA enrollment completes) — lets a second
    # POST /setup/admin call (e.g. after a browser crash mid-setup) reuse
    # the same account instead of creating a second one. ON DELETE SET NULL
    # only matters if that row is later removed by a direct DB edit; normal
    # application code never deletes users.
    setup_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))

    # Argon2 hash of the console-issued one-time setup token (Section 9) —
    # reuses app/core/security.py's existing hash_password/verify_password,
    # not a second hashing scheme. Regenerated on every backend startup
    # while uninitialized (see app/main.py's startup hook), so a lost token
    # is recoverable by restarting the container rather than by any DB
    # access. Never the plaintext token, never reused as a session or MFA
    # token.
    setup_token_hash: Mapped[str | None] = mapped_column(String(255))
