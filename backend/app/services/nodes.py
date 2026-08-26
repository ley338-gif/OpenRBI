import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.session_agent_client import NodeConnection
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


async def get_node(db: AsyncSession, node_id: uuid.UUID | None) -> BrowserNode | None:
    """Small convenience wrapper so every connection_for_node() call site
    doesn't need its own `if node_id else None` guard — BrowserSession.node_id
    is nullable (a pre-multi-node-readiness row, or a row that failed
    before node selection).
    """
    return await db.get(BrowserNode, node_id) if node_id else None


def connection_for_node(node: BrowserNode | None) -> NodeConnection:
    """Roadmap B2.2 — resolves which Session Agent to actually talk to for
    a given node. A node enrolled via B2.1 (enroll_node()) has both
    endpoint_url and agent_token_encrypted set once approved; a node
    created via the legacy single-node auto-registration path
    (refresh_node_from_agent(), driven by the operator's own trusted .env
    config) has neither — falls back to the single shared
    session_agent_base_url/api_token exactly as every call did before this
    phase, so that path's behavior is unchanged. `node=None` (a caller with
    no resolvable node at all) falls back the same way, rather than
    raising — matches the existing "the legacy default is always
    reachable" assumption the single-node case already made.

    Pure/sync on purpose: the caller is responsible for loading `node`
    (it's already an ORM object at every call site in this codebase, never
    just an id), so this needs no DB access of its own.
    """
    if node is not None and node.endpoint_url and node.agent_token_encrypted:
        return NodeConnection(base_url=node.endpoint_url, token=decrypt_secret(node.agent_token_encrypted))
    settings = get_settings()
    return NodeConnection(base_url=settings.session_agent_base_url, token=settings.session_agent_api_token)
