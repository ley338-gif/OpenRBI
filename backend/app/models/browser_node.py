from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import BrowserNodeStatus
from app.models.mixins import CreatedAtMixin, UUIDPKMixin


class BrowserNode(UUIDPKMixin, CreatedAtMixin, Base):
    """Modeled as a first-class entity even though MVP 1 runs a single node,
    so multi-node scheduling can be added later without a schema change
    (see docs/architecture.md#multi-node-readiness).
    """

    __tablename__ = "browser_nodes"

    # The Session Agent's configured OPENRBI_AGENT_NODE_NAME, not a literal
    # OS hostname — using the container's actual hostname here caused a
    # real bug (Phase 18): it's ephemeral and changes on every container
    # recreation, silently orphaning a new BrowserNode row each time.
    hostname: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[BrowserNodeStatus] = mapped_column(
        Enum(BrowserNodeStatus, name="browser_node_status"), nullable=False,
        default=BrowserNodeStatus.OFFLINE,
    )
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    runtime: Mapped[str] = mapped_column(String(64), nullable=False, default="docker")
    version: Mapped[str | None] = mapped_column(String(64))
