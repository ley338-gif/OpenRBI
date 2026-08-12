import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.user import User
from app.services.mfa import reset_mfa

router = APIRouter(prefix="/mfa/admin", tags=["admin"], dependencies=[Depends(require_role("ADMIN"))])


@router.post("/users/{user_id}/reset")
async def admin_reset_mfa(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Admin-triggered MFA reset. Always generates a security event (see
    docs/adr/0002-totp-mfa.md).

    Split out of app/api/mfa.py (Productization v0.1.1, docs/adr/
    0011-user-admin-listener-separation.md): this was previously the one
    admin-only endpoint living inside an otherwise shared/user-facing
    router, which would have forced admin_mfa's route into a user-mode
    listener too. Business logic is unchanged — only the router/module it
    lives in moved.
    """
    target_user = await db.get(User, user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    await reset_mfa(db, target_user, current_user.id)
    await db.commit()
    return {"status": "ok"}
