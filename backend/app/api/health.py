from fastapi import APIRouter

from app.build_info import BUILD_INFO

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health() -> dict[str, str]:
    """Liveness check. Dependency health (DB/Redis/Session Agent/scanner) is
    added in Phase 19 (Health Monitoring) — this endpoint intentionally does
    not claim dependencies are healthy yet.
    """
    return {"status": "ok", **BUILD_INFO.as_dict()}
