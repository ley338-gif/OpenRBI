import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt_secret
from app.models.browser_node import BrowserNode
from app.models.enums import BrowserNodeStatus, NodeEnrollmentStatus, SecurityEventType
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


async def enroll_node(db: AsyncSession, *, hostname: str, api_token: str) -> BrowserNode:
    """Roadmap B2.1 (docs/adr/0023-node-enrollment-and-trust-model.md) —
    called only after the caller (app/api/node_enrollment.py) has already
    verified a valid, single-use enrollment token.

    `hostname` is unique at the DB level, so re-enrollment needs explicit
    handling: a REVOKED row for this hostname is reset back to PENDING
    with the freshly reported token (re-enrolling a physically replaced
    or reset host, without ever skipping the approval step again — this
    only resets enrollment_status, never sets it to APPROVED). Any other
    existing status (PENDING/APPROVED) means this hostname is already
    live or already awaiting a decision, and re-enrolling it would let a
    second, possibly different agent silently take over that identity —
    rejected outright.
    """
    result = await db.execute(select(BrowserNode).where(BrowserNode.hostname == hostname))
    existing = result.scalar_one_or_none()
    if existing is not None and existing.enrollment_status != NodeEnrollmentStatus.REVOKED:
        raise NodeServiceError(f"hostname already registered (enrollment_status={existing.enrollment_status.value})")

    if existing is not None:
        node = existing
        node.status = BrowserNodeStatus.OFFLINE
        node.enrollment_status = NodeEnrollmentStatus.PENDING
        node.endpoint_url = None
    else:
        node = BrowserNode(hostname=hostname, status=BrowserNodeStatus.OFFLINE, enrollment_status=NodeEnrollmentStatus.PENDING)
    node.agent_token_encrypted = encrypt_secret(api_token)
    db.add(node)
    await db.flush()
    await record_security_event(
        db, SecurityEventType.NODE_ENROLLMENT_REQUESTED, metadata={"node_id": str(node.id), "hostname": hostname}
    )
    await db.flush()
    return node


async def approve_node(db: AsyncSession, node: BrowserNode, *, endpoint_url: str, actor_id: uuid.UUID) -> None:
    if node.enrollment_status == NodeEnrollmentStatus.REVOKED:
        raise NodeServiceError("cannot approve a revoked node — re-enroll it first")
    if node.enrollment_status == NodeEnrollmentStatus.APPROVED and node.endpoint_url == endpoint_url:
        return  # idempotent
    node.enrollment_status = NodeEnrollmentStatus.APPROVED
    node.endpoint_url = endpoint_url
    db.add(node)
    await record_security_event(
        db,
        SecurityEventType.NODE_APPROVED,
        user_id=actor_id,
        metadata={"actor": str(actor_id), "node_id": str(node.id), "endpoint_url": endpoint_url},
    )
    await db.flush()


async def revoke_node(db: AsyncSession, node: BrowserNode, *, actor_id: uuid.UUID) -> None:
    """Terminal for this row: clears the stored token (nothing should be
    able to authenticate as this node again) and marks it OFFLINE so it
    immediately drops out of anything that only checks `status`. Re-adding
    this host requires a fresh enrollment token and a new row — see
    enroll_node()'s own note on why it never reuses an existing hostname.
    """
    if node.enrollment_status == NodeEnrollmentStatus.REVOKED:
        return  # idempotent
    node.enrollment_status = NodeEnrollmentStatus.REVOKED
    node.status = BrowserNodeStatus.OFFLINE
    node.agent_token_encrypted = None
    db.add(node)
    await record_security_event(
        db, SecurityEventType.NODE_REVOKED, user_id=actor_id, metadata={"actor": str(actor_id), "node_id": str(node.id)}
    )
    await db.flush()
