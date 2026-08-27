import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import UUIDPKMixin


class WorkerMetricSample(UUIDPKMixin, Base):
    """Roadmap Phase B / B1.10.2 — the small internal metrics-history table
    the task explicitly allows in place of standing up Prometheus/Grafana
    for MVP 1: one row per worker per poll tick (app/core/node_poller.py,
    same 15s interval as the live telemetry it's a snapshot of), pruned to
    a 7-day retention window at insert time (app/services/metrics_history.py)
    — the longest range the dashboard's own UI offers. Answers both the
    dashboard's aggregate "active sessions over time" graph (summed across
    workers per time bucket) and, later, a per-worker CPU/RAM/sessions
    graph (Roadmap B1.10.3) from this one table — never a second
    time-series store for one of those and not the other.
    """

    __tablename__ = "worker_metric_samples"

    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("browser_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    cpu_percent: Mapped[float | None] = mapped_column(Float)
    ram_used_mb: Mapped[int | None] = mapped_column(Integer)
    ram_total_mb: Mapped[int | None] = mapped_column(Integer)
    active_sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Roadmap B3.3 — snapshot of BrowserNode.capacity_bound at sample time,
    # so app/services/dashboard.py can check "bound by real headroom for
    # every recent sample" the same way it already does for sustained high
    # CPU, without a second time-series table.
    capacity_bound: Mapped[str | None] = mapped_column(String(16))
