import uuid

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.sessions import get_session
from app.db.session import get_db
from app.models.role import Role
from app.models.user import User

settings = get_settings()


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
) -> User:
    """Fails closed: any missing/invalid/expired session, or a user that is
    no longer active, is a 401 — never a silent fallback identity.
    """
    if session_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")

    session = await get_session(session_token)
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session expired or invalid")

    user = await db.get(User, uuid.UUID(session["user_id"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="account not active")

    return user


def require_role(*allowed_role_names: str):
    """Minimal role gate used ahead of the full authorization framework
    (Phase 5). Fails closed: a user whose role isn't in the allowed set, or
    whose role can't be resolved, is a 403 — never an implicit allow.
    """

    async def _check(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        role = await db.get(Role, current_user.role_id)
        if role is None or role.name not in allowed_role_names:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role")
        return current_user

    return _check
