"""Roadmap Phase B / B1.10.2 — GET /admin/dashboard, the single aggregation
endpoint backing the Operations Dashboard. Read-only, same RBAC as every
other admin read surface (ADMIN + SECURITY_REVIEWER).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.dashboard import DashboardResponse
from app.core.deps import require_role
from app.db.session import get_db
from app.services.dashboard import get_dashboard
from app.services.metrics_history import RANGE_CONFIG

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_role("ADMIN", "SECURITY_REVIEWER"))])


@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard_endpoint(range: str = "24h", db: AsyncSession = Depends(get_db)) -> DashboardResponse:
    if range not in RANGE_CONFIG:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"range must be one of {sorted(RANGE_CONFIG)}"
        )
    dashboard = await get_dashboard(db, range_key=range)
    return DashboardResponse.from_dashboard(dashboard)
