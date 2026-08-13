from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.admin import LoginDiagnosticsResponse
from app.core.deps import require_role
from app.db.session import get_db
from app.services.login_diagnostics import diagnose_login

# Roadmap B1.10.6 — read-only, ADMIN/SECURITY_REVIEWER (matching the
# dashboard's and Workers' own read access), separate from admin.py's
# ADMIN-only user-management router since this endpoint isn't scoped to a
# known user_id — it accepts any username, including ones that turn out
# not to exist, since "why can't user X log in" often starts with "does
# this account even exist."
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_role("ADMIN", "SECURITY_REVIEWER"))])


@router.get("/login-diagnostics", response_model=LoginDiagnosticsResponse)
async def login_diagnostics(username: str, db: AsyncSession = Depends(get_db)) -> LoginDiagnosticsResponse:
    return LoginDiagnosticsResponse(**await diagnose_login(db, username))
