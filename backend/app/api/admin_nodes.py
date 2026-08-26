import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.nodes import (
    BrowserNodeResponse,
    NodeApproveRequest,
    NodeEnrollmentTokenResponse,
    NodeHistoryPointResponse,
    WorkerOverviewResponse,
    WorkerOverviewStats,
)
from app.core.deps import get_current_user, require_role
from app.core.node_enrollment_tokens import TTL_SECONDS as ENROLLMENT_TOKEN_TTL_SECONDS
from app.core.node_enrollment_tokens import create_token as create_enrollment_token
from app.db.session import get_db
from app.models.browser_node import BrowserNode
from app.models.user import User
from app.services import metrics_history
from app.services.metrics_history import RANGE_CONFIG
from app.services.nodes import (
    NodeServiceError,
    approve_node,
    drain_node,
    maintenance_node,
    revoke_node,
    undrain_node,
    unmaintenance_node,
)

# ADMIN and SECURITY_REVIEWER can both read node state/history (matching the
# dashboard's own read access); only ADMIN can drain/undrain/maintenance —
# enforced per-route below, not at the router level, since the router-level
# dependency would otherwise also gate the read-only GETs to ADMIN-only.
router = APIRouter(prefix="/admin/nodes", tags=["admin"], dependencies=[Depends(require_role("ADMIN", "SECURITY_REVIEWER"))])


async def _get_or_404(db: AsyncSession, node_id: uuid.UUID) -> BrowserNode:
    node = await db.get(BrowserNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="node not found")
    return node


@router.get("", response_model=list[BrowserNodeResponse])
async def list_nodes(db: AsyncSession = Depends(get_db)) -> list[BrowserNodeResponse]:
    result = await db.execute(select(BrowserNode).order_by(BrowserNode.hostname))
    return [BrowserNodeResponse.from_model(n) for n in result.scalars()]


@router.get("/overview", response_model=WorkerOverviewResponse)
async def worker_overview(
    search: str | None = None,
    health: str | None = None,
    node_status: str | None = None,
    sort_by: str = "hostname",
    sort_dir: str = "asc",
    offset: int = 0,
    limit: int = 25,
    db: AsyncSession = Depends(get_db),
) -> WorkerOverviewResponse:
    if offset < 0 or limit < 1 or limit > 100:
        raise HTTPException(status_code=422, detail="invalid pagination")
    nodes = (await db.execute(select(BrowserNode))).scalars().all()
    responses = [BrowserNodeResponse.from_model(node) for node in nodes]
    cpu_values = [node.cpu_percent for node in responses if node.cpu_percent is not None]
    ram_values = [
        node.ram_used_mb / node.ram_total_mb * 100
        for node in responses
        if node.ram_total_mb and node.ram_used_mb is not None
    ]
    stats = WorkerOverviewStats(
        total=len(responses),
        healthy=sum(node.health == "HEALTHY" for node in responses),
        needs_attention=sum(node.health in {"DEGRADED", "OFFLINE"} for node in responses),
        active_sessions=sum(node.active_sessions for node in responses),
        total_capacity=sum(node.capacity for node in responses),
        average_cpu_percent=sum(cpu_values) / len(cpu_values) if cpu_values else None,
        average_ram_percent=sum(ram_values) / len(ram_values) if ram_values else None,
        latest_heartbeat=max((node.last_heartbeat for node in responses if node.last_heartbeat), default=None),
    )
    filtered = responses
    if search:
        needle = search.casefold()
        filtered = [node for node in filtered if needle in node.hostname.casefold()]
    if health:
        filtered = [node for node in filtered if node.health == health]
    if node_status:
        filtered = [node for node in filtered if node.status == node_status]
    if sort_by not in {"hostname", "health", "cpu", "ram", "sessions", "heartbeat"} or sort_dir not in {"asc", "desc"}:
        raise HTTPException(status_code=422, detail="invalid sort")

    def ram_percent(node: BrowserNodeResponse) -> float:
        return node.ram_used_mb / node.ram_total_mb * 100 if node.ram_total_mb and node.ram_used_mb is not None else -1

    keys = {
        "hostname": lambda node: node.hostname.casefold(),
        "health": lambda node: node.health,
        "cpu": lambda node: node.cpu_percent if node.cpu_percent is not None else -1,
        "ram": ram_percent,
        "sessions": lambda node: node.active_sessions,
        "heartbeat": lambda node: node.last_heartbeat or datetime.min.replace(tzinfo=UTC),
    }
    filtered.sort(key=keys[sort_by], reverse=sort_dir == "desc")
    return WorkerOverviewResponse(
        items=filtered[offset : offset + limit],
        total=len(filtered),
        offset=offset,
        limit=limit,
        stats=stats,
    )


@router.get("/{node_id}", response_model=BrowserNodeResponse)
async def get_node(node_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> BrowserNodeResponse:
    node = await _get_or_404(db, node_id)
    return BrowserNodeResponse.from_model(node)


@router.get("/{node_id}/metrics", response_model=list[NodeHistoryPointResponse])
async def get_node_metrics(
    node_id: uuid.UUID, range: str = "24h", db: AsyncSession = Depends(get_db)
) -> list[NodeHistoryPointResponse]:
    if range not in RANGE_CONFIG:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"range must be one of {sorted(RANGE_CONFIG)}")
    await _get_or_404(db, node_id)  # 404 before querying history for a nonexistent node
    points = await metrics_history.node_history(db, node_id=node_id, range_key=range)
    return [NodeHistoryPointResponse(**p) for p in points]


@router.post("/{node_id}/drain", response_model=BrowserNodeResponse, dependencies=[Depends(require_role("ADMIN"))])
async def drain_node_endpoint(
    node_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> BrowserNodeResponse:
    node = await _get_or_404(db, node_id)
    await drain_node(db, node, actor_id=current_user.id)
    await db.commit()
    await db.refresh(node)
    return BrowserNodeResponse.from_model(node)


@router.post("/{node_id}/undrain", response_model=BrowserNodeResponse, dependencies=[Depends(require_role("ADMIN"))])
async def undrain_node_endpoint(
    node_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> BrowserNodeResponse:
    node = await _get_or_404(db, node_id)
    try:
        await undrain_node(db, node, actor_id=current_user.id)
    except NodeServiceError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(node)
    return BrowserNodeResponse.from_model(node)


@router.post("/{node_id}/maintenance", response_model=BrowserNodeResponse, dependencies=[Depends(require_role("ADMIN"))])
async def maintenance_node_endpoint(
    node_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> BrowserNodeResponse:
    node = await _get_or_404(db, node_id)
    try:
        await maintenance_node(db, node, actor_id=current_user.id)
    except NodeServiceError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(node)
    return BrowserNodeResponse.from_model(node)


@router.post("/{node_id}/unmaintenance", response_model=BrowserNodeResponse, dependencies=[Depends(require_role("ADMIN"))])
async def unmaintenance_node_endpoint(
    node_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> BrowserNodeResponse:
    node = await _get_or_404(db, node_id)
    try:
        await unmaintenance_node(db, node, actor_id=current_user.id)
    except NodeServiceError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(node)
    return BrowserNodeResponse.from_model(node)


# Roadmap B2.1 (docs/adr/0023-node-enrollment-and-trust-model.md) — ADMIN
# only, matching drain/maintenance above: generating a credential that
# lets a new host register at all is at least as sensitive as pausing an
# existing one.
@router.post(
    "/enrollment-tokens", response_model=NodeEnrollmentTokenResponse, dependencies=[Depends(require_role("ADMIN"))]
)
async def create_enrollment_token_endpoint() -> NodeEnrollmentTokenResponse:
    token = await create_enrollment_token()
    return NodeEnrollmentTokenResponse(enrollment_token=token, expires_in_seconds=ENROLLMENT_TOKEN_TTL_SECONDS)


@router.post("/{node_id}/approve", response_model=BrowserNodeResponse, dependencies=[Depends(require_role("ADMIN"))])
async def approve_node_endpoint(
    node_id: uuid.UUID,
    payload: NodeApproveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BrowserNodeResponse:
    node = await _get_or_404(db, node_id)
    try:
        await approve_node(db, node, endpoint_url=payload.endpoint_url, actor_id=current_user.id)
    except NodeServiceError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(node)
    return BrowserNodeResponse.from_model(node)


@router.post("/{node_id}/revoke", response_model=BrowserNodeResponse, dependencies=[Depends(require_role("ADMIN"))])
async def revoke_node_endpoint(
    node_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> BrowserNodeResponse:
    node = await _get_or_404(db, node_id)
    await revoke_node(db, node, actor_id=current_user.id)
    await db.commit()
    await db.refresh(node)
    return BrowserNodeResponse.from_model(node)
