from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.health import SystemHealthResponse
from app.core.deps import require_role
from app.db.session import get_db
from app.services.health import get_system_health

router = APIRouter(
    prefix="/admin/health",
    tags=["admin"],
    dependencies=[Depends(require_role("ADMIN", "SECURITY_REVIEWER"))],
)


@router.get("", response_model=SystemHealthResponse)
async def system_health(db: AsyncSession = Depends(get_db)) -> SystemHealthResponse:
    health = await get_system_health(db)
    return SystemHealthResponse.from_model(health)
