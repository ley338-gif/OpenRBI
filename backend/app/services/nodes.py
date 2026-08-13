import uuid

from app.models.browser_node import BrowserNode
from app.models.enums import BrowserNodeStatus, SecurityEventType
from app.services.security_events import record_security_event


class NodeServiceError(ValueError):
    pass


async def drain_node(db, node: BrowserNode, *, actor_id: uuid.UUID) -> None:
    """DRAINING: no new sessions are scheduled onto this node, but existing
    sessions keep running (project brief §23) — select_node() in
    app/services/sessions.py refuses new sessions for any non-ONLINE node,
    and separately never lets its own heartbeat refresh overwrite this
    admin-set status back to ONLINE.
    """
    if node.status == BrowserNodeStatus.DRAINING:
        return  # idempotent
    if node.status == BrowserNodeStatus.MAINTENANCE:
        raise NodeServiceError("node is in maintenance — disable maintenance first")
    node.status = BrowserNodeStatus.DRAINING
    db.add(node)
    await record_security_event(
        db, SecurityEventType.WORKER_DRAIN_ENABLED, metadata={"actor": str(actor_id), "node_id": str(node.id)}
    )
    await db.flush()


async def undrain_node(db, node: BrowserNode, *, actor_id: uuid.UUID) -> None:
    """Reactivates a drained node. The logical, necessary complement to
    draining — without it a drained node has no way back to ONLINE, since
    the Session Agent's own heartbeat never reports DRAINING in the first
    place for select_node() to correct.
    """
    if node.status != BrowserNodeStatus.DRAINING:
        raise NodeServiceError(f"node is not draining (status={node.status.value})")
    node.status = BrowserNodeStatus.ONLINE
    db.add(node)
    await record_security_event(
        db, SecurityEventType.WORKER_DRAIN_DISABLED, metadata={"actor": str(actor_id), "node_id": str(node.id)}
    )
    await db.flush()


async def maintenance_node(db, node: BrowserNode, *, actor_id: uuid.UUID) -> None:
    """MAINTENANCE: unlike DRAINING, the node is fully excluded from the
    scheduler regardless of whether it currently has capacity or sessions
    — an admin took it out of service on purpose (Roadmap B1.10.1). Does
    NOT terminate existing sessions on it; that's a separate, explicit
    session-administration action (Roadmap B1.10.4), never an implicit
    side effect of a status change.
    """
    if node.status == BrowserNodeStatus.MAINTENANCE:
        return  # idempotent
    node.status = BrowserNodeStatus.MAINTENANCE
    db.add(node)
    await record_security_event(
        db, SecurityEventType.WORKER_MAINTENANCE_ENABLED, metadata={"actor": str(actor_id), "node_id": str(node.id)}
    )
    await db.flush()


async def unmaintenance_node(db, node: BrowserNode, *, actor_id: uuid.UUID) -> None:
    if node.status != BrowserNodeStatus.MAINTENANCE:
        raise NodeServiceError(f"node is not in maintenance (status={node.status.value})")
    node.status = BrowserNodeStatus.ONLINE
    db.add(node)
    await record_security_event(
        db,
        SecurityEventType.WORKER_MAINTENANCE_DISABLED,
        metadata={"actor": str(actor_id), "node_id": str(node.id)},
    )
    await db.flush()
