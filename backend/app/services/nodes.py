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
    node.status = BrowserNodeStatus.DRAINING
    db.add(node)
    await record_security_event(
        db, SecurityEventType.NODE_DRAINED, metadata={"actor": str(actor_id), "node_id": str(node.id)}
    )
    await db.flush()


async def undrain_node(db, node: BrowserNode, *, actor_id: uuid.UUID) -> None:
    """Reactivates a drained node. Not itself in the project brief's
    minimum event list, but the logical, necessary complement to draining
    — without it a drained node has no way back to ONLINE, since the
    Session Agent's own heartbeat never reports DRAINING in the first
    place for select_node() to correct.
    """
    if node.status != BrowserNodeStatus.DRAINING:
        raise NodeServiceError(f"node is not draining (status={node.status.value})")
    node.status = BrowserNodeStatus.ONLINE
    db.add(node)
    await db.flush()
