import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.nodes import BrowserNodeResponse
from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.browser_node import BrowserNode
from app.models.user import User
from app.services.nodes import NodeServiceError, drain_node, maintenance_node, undrain_node, unmaintenance_node

router = APIRouter(prefix="/admin/nodes", tags=["admin"], dependencies=[Depends(require_role("ADMIN"))])


async def _get_or_404(db: AsyncSession, node_id: uuid.UUID) -> BrowserNode:
    node = await db.get(BrowserNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="node not found")
    return node


@router.get("", response_model=list[BrowserNodeResponse])
async def list_nodes(db: AsyncSession = Depends(get_db)) -> list[BrowserNodeResponse]:
    result = await db.execute(select(BrowserNode).order_by(BrowserNode.hostname))
    return [BrowserNodeResponse.from_model(n) for n in result.scalars()]


@router.post("/{node_id}/drain", response_model=BrowserNodeResponse)
async def drain_node_endpoint(
    node_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> BrowserNodeResponse:
    node = await _get_or_404(db, node_id)
    await drain_node(db, node, actor_id=current_user.id)
    await db.commit()
    await db.refresh(node)
    return BrowserNodeResponse.from_model(node)


@router.post("/{node_id}/undrain", response_model=BrowserNodeResponse)
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


@router.post("/{node_id}/maintenance", response_model=BrowserNodeResponse)
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


@router.post("/{node_id}/unmaintenance", response_model=BrowserNodeResponse)
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
