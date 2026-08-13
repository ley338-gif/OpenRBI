import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.admin import (
    CreateGroupRequest,
    CreateUserRequest,
    GroupSummary,
    ResetPasswordRequest,
    SetUserGroupsRequest,
    UpdateUserRoleRequest,
    UserSummary,
)
from app.api.display import force_disconnect
from app.api.schemas.sessions import AdminSessionResponse, RevokeSessionsResponse
from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.browser_session import BrowserSession
from app.models.role import Role
from app.models.user import User
from app.models.group import Group
from app.services.groups import GroupServiceError, create_group, delete_group, list_groups_with_member_counts
from app.services.sessions import revoke_user_sessions
from app.services.users import (
    UserServiceError,
    change_role,
    create_user,
    get_group_names,
    reset_password,
    set_active,
    set_groups,
)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_role("ADMIN"))])


async def _to_summary(db: AsyncSession, user: User) -> UserSummary:
    role = await db.get(Role, user.role_id)
    groups = await get_group_names(db, user.id)
    return UserSummary(
        id=user.id,
        username=user.username,
        role=role.name,
        is_active=user.is_active,
        mfa_enabled=user.mfa_enabled,
        groups=groups,
        created_at=user.created_at,
    )


@router.get("/users", response_model=list[UserSummary])
async def list_users(db: AsyncSession = Depends(get_db)) -> list[UserSummary]:
    result = await db.execute(select(User).order_by(User.username))
    return [await _to_summary(db, u) for u in result.scalars()]


@router.post("/users", response_model=UserSummary, status_code=status.HTTP_201_CREATED)
async def create_user_endpoint(
    payload: CreateUserRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserSummary:
    try:
        user = await create_user(
            db,
            username=payload.username,
            password=payload.password,
            role_name=payload.role,
            group_ids=payload.group_ids,
            created_by=current_user.id,
        )
    except UserServiceError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await db.commit()
    return await _to_summary(db, user)


async def _get_user_or_404(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return user


@router.get("/users/{user_id}", response_model=UserSummary)
async def get_user(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> UserSummary:
    user = await _get_user_or_404(db, user_id)
    return await _to_summary(db, user)


@router.post("/users/{user_id}/disable", response_model=UserSummary)
async def disable_user(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserSummary:
    user = await _get_user_or_404(db, user_id)
    await set_active(db, user, active=False, actor_id=current_user.id)
    await db.commit()
    return await _to_summary(db, user)


@router.post("/users/{user_id}/enable", response_model=UserSummary)
async def enable_user(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserSummary:
    user = await _get_user_or_404(db, user_id)
    await set_active(db, user, active=True, actor_id=current_user.id)
    await db.commit()
    return await _to_summary(db, user)


@router.post("/users/{user_id}/reset-password")
async def reset_password_endpoint(
    user_id: uuid.UUID,
    payload: ResetPasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    user = await _get_user_or_404(db, user_id)
    await reset_password(db, user, new_password=payload.new_password, actor_id=current_user.id)
    await db.commit()
    return {"status": "ok"}


@router.put("/users/{user_id}/role", response_model=UserSummary)
async def update_role(
    user_id: uuid.UUID,
    payload: UpdateUserRoleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserSummary:
    user = await _get_user_or_404(db, user_id)
    try:
        await change_role(db, user, role_name=payload.role, actor_id=current_user.id)
    except UserServiceError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return await _to_summary(db, user)


@router.put("/users/{user_id}/groups", response_model=UserSummary)
async def update_groups(
    user_id: uuid.UUID,
    payload: SetUserGroupsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserSummary:
    user = await _get_user_or_404(db, user_id)
    try:
        await set_groups(db, user, group_ids=payload.group_ids, actor_id=current_user.id)
    except UserServiceError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return await _to_summary(db, user)


@router.get("/groups", response_model=list[GroupSummary])
async def list_groups(db: AsyncSession = Depends(get_db)) -> list[GroupSummary]:
    rows = await list_groups_with_member_counts(db)
    return [
        GroupSummary(id=group.id, name=group.name, description=group.description, member_count=count)
        for group, count in rows
    ]


@router.post("/groups", response_model=GroupSummary, status_code=status.HTTP_201_CREATED)
async def create_group_endpoint(
    payload: CreateGroupRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GroupSummary:
    try:
        group = await create_group(db, name=payload.name, description=payload.description, actor_id=current_user.id)
    except GroupServiceError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return GroupSummary(id=group.id, name=group.name, description=group.description, member_count=0)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group_endpoint(
    group_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    group = await db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="group not found")
    await delete_group(db, group, actor_id=current_user.id)
    await db.commit()


@router.get("/users/{user_id}/sessions", response_model=list[AdminSessionResponse])
async def list_user_sessions(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> list[AdminSessionResponse]:
    """Convenience view for the User Detail page (project brief §26: "Admin
    sieht die aktive Browser-Session"). Full session control actions
    (disconnect/isolate/restore/kill) live under /admin/sessions
    (app/api/admin_sessions.py), not duplicated here.
    """
    user = await _get_user_or_404(db, user_id)
    result = await db.execute(
        select(BrowserSession).where(BrowserSession.user_id == user.id).order_by(BrowserSession.created_at.desc())
    )
    return [AdminSessionResponse.from_model_with_user(s, user.username) for s in result.scalars()]


@router.post("/users/{user_id}/sessions/revoke", response_model=RevokeSessionsResponse)
async def revoke_sessions(
    user_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> RevokeSessionsResponse:
    """Roadmap B1.10.4 — bulk termination, the by-user counterpart to
    /admin/sessions/{id}/kill. ADMIN-only (this whole router is), matching
    Kill's own restriction rather than SECURITY_REVIEWER's broader
    disconnect/isolate access.
    """
    user = await _get_user_or_404(db, user_id)
    terminated = await revoke_user_sessions(db, user, actor_id=current_user.id)
    await db.commit()
    for session in terminated:
        await force_disconnect(session.id)
    return RevokeSessionsResponse(terminated_count=len(terminated), session_ids=[s.id for s in terminated])
