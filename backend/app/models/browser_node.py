from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, Integer, String
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

    # Roadmap B1.10.1 — host-wide telemetry self-reported by the Session
    # Agent (session-agent/app/main.py's /v1/nodes/self), refreshed by both
    # select_node() (on session creation) and app/core/node_poller.py (on a
    # fixed interval, so the dashboard stays current even with no session
    # traffic). All nullable: a node that has never successfully reported
    # has none of this yet, and app/services/worker_health.py treats that
    # the same as a stale heartbeat (OFFLINE), never as 0%/idle.
    cpu_percent: Mapped[float | None] = mapped_column(Float)
    ram_total_mb: Mapped[int | None] = mapped_column(Integer)
    ram_used_mb: Mapped[int | None] = mapped_column(Integer)
    # When the Session Agent process serving this node last started —
    # "worker uptime" in the admin UI is `now - node_started_at`, computed
    # at read time rather than stored as a duration that would need
    # constant re-writing to stay accurate.
    node_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
