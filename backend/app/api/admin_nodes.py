import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.nodes import BrowserNodeResponse, NodeHistoryPointResponse
from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.browser_node import BrowserNode
from app.models.user import User
from app.services import metrics_history
from app.services.metrics_history import RANGE_CONFIG
from app.services.nodes import NodeServiceError, drain_node, maintenance_node, undrain_node, unmaintenance_node

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
