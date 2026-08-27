"""Roadmap Phase B / B1.10.2 — records and queries the small internal
worker-metrics history (app/models/worker_metric_sample.py). Deliberately
not a general time-series abstraction: the two things a caller can ask for
are "record what a node looks like right now" and "give me a bucketed
history for a given lookback window," because those are the only two
things the dashboard/worker-detail graphs actually need.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.browser_node import BrowserNode
from app.models.worker_metric_sample import WorkerMetricSample

# Time range -> (lookback, bucket width). Bucket width is chosen so a 7d
# range still returns a manageable number of points (168) instead of one
# per 15s poll tick (~40,000) — real aggregation, not decimation: each
# bucket averages every sample that landed in it.
RANGE_CONFIG: dict[str, tuple[timedelta, timedelta]] = {
    "1h": (timedelta(hours=1), timedelta(minutes=1)),
    "6h": (timedelta(hours=6), timedelta(minutes=5)),
    "24h": (timedelta(hours=24), timedelta(minutes=15)),
    "7d": (timedelta(days=7), timedelta(hours=1)),
}


async def record_sample(db: AsyncSession, node: BrowserNode, *, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    db.add(
        WorkerMetricSample(
            node_id=node.id,
            recorded_at=now,
            cpu_percent=node.cpu_percent,
            ram_used_mb=node.ram_used_mb,
            ram_total_mb=node.ram_total_mb,
            active_sessions=node.active_sessions,
            capacity_bound=node.capacity_bound,
        )
    )
    settings = get_settings()
    cutoff = now - timedelta(days=settings.metrics_retention_days)
    await db.execute(delete(WorkerMetricSample).where(WorkerMetricSample.recorded_at < cutoff))
    await db.flush()


async def session_history(db: AsyncSession, *, range_key: str, now: datetime | None = None) -> list[dict]:
    """Total active sessions across every worker, bucketed. Sums samples
    per bucket per node first (so two workers polled at slightly different
    times within the same bucket both count), then sums across nodes.
    """
    if range_key not in RANGE_CONFIG:
        raise ValueError(f"unknown range: {range_key}")
    lookback, bucket_width = RANGE_CONFIG[range_key]
    now = now or datetime.now(UTC)
    since = now - lookback

    bucket = func.date_bin(bucket_width, WorkerMetricSample.recorded_at, since)
    # Per-node-per-bucket average first, then sum across nodes — avoids a
    # node that happened to report twice in one bucket outweighing one
    # that only reported once.
    per_node = (
        select(
            bucket.label("bucket"),
            WorkerMetricSample.node_id,
            func.avg(WorkerMetricSample.active_sessions).label("avg_sessions"),
        )
        .where(WorkerMetricSample.recorded_at >= since)
        .group_by("bucket", WorkerMetricSample.node_id)
        .subquery()
    )
    result = await db.execute(
        select(per_node.c.bucket, func.sum(per_node.c.avg_sessions))
        .group_by(per_node.c.bucket)
        .order_by(per_node.c.bucket)
    )
    return [{"t": row[0], "count": round(float(row[1]))} for row in result.all()]


async def node_history(db: AsyncSession, *, node_id: uuid.UUID, range_key: str, now: datetime | None = None) -> list[dict]:
    """Bucketed CPU/RAM/session history for a single worker (Worker Detail
    view, Roadmap B1.10.3) — same bucketing as session_history() above, but
    scoped to one node's own samples instead of summed across the fleet.
    """
    if range_key not in RANGE_CONFIG:
        raise ValueError(f"unknown range: {range_key}")
    lookback, bucket_width = RANGE_CONFIG[range_key]
    now = now or datetime.now(UTC)
    since = now - lookback

    bucket = func.date_bin(bucket_width, WorkerMetricSample.recorded_at, since)
    result = await db.execute(
        select(
            bucket.label("bucket"),
            func.avg(WorkerMetricSample.cpu_percent),
            func.avg(WorkerMetricSample.ram_used_mb),
            func.avg(WorkerMetricSample.ram_total_mb),
            func.avg(WorkerMetricSample.active_sessions),
        )
        .where(WorkerMetricSample.recorded_at >= since, WorkerMetricSample.node_id == node_id)
        .group_by("bucket")
        .order_by("bucket")
    )
    points = []
    for t, cpu, ram_used, ram_total, sessions in result.all():
        ram_percent = round(float(ram_used) / float(ram_total) * 100, 1) if ram_used is not None and ram_total else None
        points.append(
            {
                "t": t,
                "cpu_percent": round(float(cpu), 1) if cpu is not None else None,
                "ram_percent": ram_percent,
                "active_sessions": round(float(sessions)) if sessions is not None else 0,
            }
        )
    return points
