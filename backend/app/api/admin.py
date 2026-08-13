import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.admin import (
    CreateGroupRequest,
    CreateUserRequest,
    GroupOverviewItem,
    GroupOverviewResponse,
    GroupOverviewStats,
    GroupSummary,
    LockoutStatus,
    ResetPasswordRequest,
    SetUserGroupsRequest,
    UpdateUserRoleRequest,
    UserListResponse,
    UserManagementStats,
    UserSummary,
)
from app.api.display import force_disconnect
from app.api.schemas.sessions import AdminSessionResponse, RevokeSessionsResponse
from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.browser_session import BrowserSession
from app.models.enums import SecurityEventType
from app.models.group import Group, UserGroup
from app.models.policy import GroupPolicy, Policy
from app.models.role import Role
from app.models.security_event import SecurityEvent
from app.models.user import User
from app.services.groups import GroupServiceError, create_group, delete_group, list_groups_with_member_counts
from app.services.sessions import revoke_user_sessions
from app.services.users import (
    UserServiceError,
    change_role,
    create_user,
    get_group_names,
    get_lockout_status,
    lock_account,
    reset_password,
    set_active,
    set_groups,
    unlock_account,
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
        auth_source="LOCAL" if user.password_hash is not None else "LDAP",
        last_login_at=None,
    )


@router.get("/users", response_model=UserListResponse)
async def list_users(
    search: str | None = None,
    role: str | None = None,
    group_id: uuid.UUID | None = None,
    account_status: str | None = Query(default=None, alias="status"),
    auth_source: str | None = None,
    mfa: str | None = None,
    sort_by: str = "username",
    sort_dir: str = "asc",
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> UserListResponse:
    """Paginated IAM overview. Only persisted fields are searchable/filterable."""
    filters = []
    if search:
        filters.append(User.username.ilike(f"%{search.strip()}%"))
    if role:
        filters.append(Role.name == role)
    if account_status == "ACTIVE":
        filters.append(User.is_active.is_(True))
    elif account_status == "DISABLED":
        filters.append(User.is_active.is_(False))
    elif account_status:
        raise HTTPException(status_code=400, detail="unknown user status")
    if auth_source == "LOCAL":
        filters.append(User.password_hash.is_not(None))
    elif auth_source == "LDAP":
        filters.append(User.password_hash.is_(None))
    elif auth_source:
        raise HTTPException(status_code=400, detail="unknown authentication source")
    if mfa == "ENABLED":
        filters.append(User.mfa_enabled.is_(True))
    elif mfa == "NOT_ENABLED":
        filters.append(User.mfa_enabled.is_(False))
    elif mfa:
        raise HTTPException(status_code=400, detail="unknown MFA filter")
    if group_id:
        filters.append(User.id.in_(select(UserGroup.user_id).where(UserGroup.group_id == group_id)))

    base = select(User, Role.name).join(Role, Role.id == User.role_id).where(*filters)
    sort_columns = {
        "username": User.username,
        "role": Role.name,
        "status": User.is_active,
        "created_at": User.created_at,
    }
    sort_column = sort_columns.get(sort_by)
    if sort_column is None or sort_dir not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="invalid sort option")
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    ordering = sort_column.desc() if sort_dir == "desc" else sort_column.asc()
    rows = (await db.execute(base.order_by(ordering).offset(offset).limit(limit))).all()
    user_ids = [user.id for user, _ in rows]

    group_names: dict[uuid.UUID, list[str]] = {user_id: [] for user_id in user_ids}
    last_logins: dict[uuid.UUID, object] = {}
    if user_ids:
        group_rows = await db.execute(
            select(UserGroup.user_id, Group.name)
            .join(Group, Group.id == UserGroup.group_id)
            .where(UserGroup.user_id.in_(user_ids))
            .order_by(Group.name)
        )
        for user_id, group_name in group_rows.all():
            group_names[user_id].append(group_name)
        login_rows = await db.execute(
            select(SecurityEvent.user_id, func.max(SecurityEvent.created_at))
            .where(
                SecurityEvent.user_id.in_(user_ids),
                SecurityEvent.event_type == SecurityEventType.USER_LOGIN,
            )
            .group_by(SecurityEvent.user_id)
        )
        last_logins = dict(login_rows.all())

    stats_row = (
        await db.execute(
            select(
                func.count(User.id),
                func.count(User.id).filter(User.is_active.is_(True)),
                func.count(User.id).filter(User.mfa_enabled.is_(True)),
            )
        )
    ).one()
    admin_count = await db.scalar(
        select(func.count(User.id)).join(Role, Role.id == User.role_id).where(Role.name == "ADMIN")
    ) or 0
    group_count = await db.scalar(select(func.count(Group.id))) or 0
    roles = list((await db.execute(select(Role.name).order_by(Role.name))).scalars())
    items = [
        UserSummary(
            id=user.id,
            username=user.username,
            role=role_name,
            is_active=user.is_active,
            mfa_enabled=user.mfa_enabled,
            groups=group_names[user.id],
            created_at=user.created_at,
            auth_source="LOCAL" if user.password_hash is not None else "LDAP",
            last_login_at=last_logins.get(user.id),
        )
        for user, role_name in rows
    ]
    return UserListResponse(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
        roles=roles,
        stats=UserManagementStats(
            total=stats_row[0],
            active=stats_row[1],
            mfa_enabled=stats_row[2],
            administrators=admin_count,
            groups=group_count,
        ),
    )


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
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="you cannot disable your own account")
    target_role = await db.get(Role, user.role_id)
    if target_role and target_role.name == "ADMIN":
        active_admins = await db.scalar(select(func.count(User.id)).join(Role).where(Role.name == "ADMIN", User.is_active.is_(True))) or 0
        if active_admins <= 1:
            raise HTTPException(status_code=400, detail="the last active administrator cannot be disabled")
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
    if user.password_hash is None:
        raise HTTPException(status_code=400, detail="password is managed by LDAP")
    await reset_password(db, user, new_password=payload.new_password, actor_id=current_user.id)
    await db.commit()
    return {"status": "ok"}


@router.get("/users/{user_id}/lockout", response_model=LockoutStatus)
async def get_lockout_status_endpoint(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> LockoutStatus:
    """Roadmap B1.10.5 — read the same brute-force-lockout state /auth/login
    itself checks (`is_login_locked`), so an admin can see whether a user
    is currently locked out (and for how much longer) before deciding
    whether to unlock them.
    """
    user = await _get_user_or_404(db, user_id)
    return LockoutStatus(**await get_lockout_status(user))


@router.post("/users/{user_id}/lock", response_model=LockoutStatus)
async def lock_account_endpoint(
    user_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> LockoutStatus:
    """Account Lock: an admin-triggered version of the same lockout the
    system already applies automatically after repeated failed logins —
    distinct from Disable (`set_active`), which is a separate, DB-persisted
    "account deactivated" state, not a login-lockout.
    """
    user = await _get_user_or_404(db, user_id)
    await lock_account(db, user, actor_id=current_user.id)
    await db.commit()
    return LockoutStatus(**await get_lockout_status(user))


@router.post("/users/{user_id}/unlock", response_model=LockoutStatus)
async def unlock_account_endpoint(
    user_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> LockoutStatus:
    user = await _get_user_or_404(db, user_id)
    await unlock_account(db, user, actor_id=current_user.id)
    await db.commit()
    return LockoutStatus(**await get_lockout_status(user))


@router.put("/users/{user_id}/role", response_model=UserSummary)
async def update_role(
    user_id: uuid.UUID,
    payload: UpdateUserRoleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserSummary:
    user = await _get_user_or_404(db, user_id)
    current_role = await db.get(Role, user.role_id)
    if current_role and current_role.name == "ADMIN" and payload.role != "ADMIN":
        active_admins = await db.scalar(
            select(func.count(User.id)).join(Role).where(Role.name == "ADMIN", User.is_active.is_(True))
        ) or 0
        if user.is_active and active_admins <= 1:
            raise HTTPException(status_code=400, detail="the last active administrator must keep the ADMIN role")
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


@router.get("/groups-overview", response_model=GroupOverviewResponse)
async def groups_overview(
    search: str | None = None,
    policy_id: uuid.UUID | None = None,
    sort_by: str = "name",
    sort_dir: str = "asc",
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> GroupOverviewResponse:
    """Paginated group operations view without per-row queries."""
    member_count = func.count(func.distinct(UserGroup.id)).label("member_count")
    base = (
        select(Group, member_count)
        .outerjoin(UserGroup, UserGroup.group_id == Group.id)
        .group_by(Group.id)
    )
    if search:
        term = f"%{search.strip()}%"
        base = base.where(or_(Group.name.ilike(term), Group.description.ilike(term)))
    if policy_id:
        base = base.where(
            Group.id.in_(select(GroupPolicy.group_id).where(GroupPolicy.policy_id == policy_id))
        )
    sort_columns = {"name": Group.name, "members": member_count, "created_at": Group.created_at}
    sort_column = sort_columns.get(sort_by)
    if sort_column is None or sort_dir not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="invalid sort option")
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    ordering = sort_column.desc() if sort_dir == "desc" else sort_column.asc()
    rows = (await db.execute(base.order_by(ordering).offset(offset).limit(limit))).all()
    group_ids = [group.id for group, _ in rows]
    policy_names: dict[uuid.UUID, list[str]] = {group_id: [] for group_id in group_ids}
    if group_ids:
        attached = await db.execute(
            select(GroupPolicy.group_id, Policy.name)
            .join(Policy, Policy.id == GroupPolicy.policy_id)
            .where(GroupPolicy.group_id.in_(group_ids))
            .order_by(Policy.name)
        )
        for group_id, policy_name in attached.all():
            policy_names[group_id].append(policy_name)

    total_groups = await db.scalar(select(func.count(Group.id))) or 0
    memberships = await db.scalar(select(func.count(UserGroup.id))) or 0
    groups_with_policies = await db.scalar(
        select(func.count(func.distinct(GroupPolicy.group_id)))
    ) or 0
    return GroupOverviewResponse(
        items=[
            GroupOverviewItem(
                id=group.id,
                name=group.name,
                description=group.description,
                member_count=count,
                policies=policy_names[group.id],
                created_at=group.created_at,
            )
            for group, count in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
        stats=GroupOverviewStats(
            total=total_groups,
            memberships=memberships,
            with_policies=groups_with_policies,
        ),
    )


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
