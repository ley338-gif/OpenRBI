import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.core.sessions import (
    clear_login_failures,
    force_login_lock,
    get_login_lockout_status,
    revoke_all_sessions_for_user,
)
from app.models.enums import SecurityEventType
from app.models.group import Group, UserGroup
from app.models.role import Role
from app.models.user import User
from app.services.security_events import record_security_event


class UserServiceError(ValueError):
    """Raised on any validation failure; callers map this to a 4xx, never a
    silent partial success (docs/adr/0008-fail-closed.md).
    """


async def _get_role_by_name(db: AsyncSession, role_name: str) -> Role:
    result = await db.execute(select(Role).where(Role.name == role_name))
    role = result.scalar_one_or_none()
    if role is None:
        raise UserServiceError(f"unknown role: {role_name}")
    return role


async def _validate_group_ids(db: AsyncSession, group_ids: list[uuid.UUID]) -> None:
    if not group_ids:
        return
    result = await db.execute(select(Group.id).where(Group.id.in_(group_ids)))
    found = {row[0] for row in result.all()}
    missing = set(group_ids) - found
    if missing:
        raise UserServiceError(f"unknown group id(s): {sorted(str(m) for m in missing)}")


async def create_user(
    db: AsyncSession,
    *,
    username: str,
    password: str,
    role_name: str,
    group_ids: list[uuid.UUID],
    created_by: uuid.UUID,
) -> User:
    result = await db.execute(select(User).where(User.username == username))
    if result.scalar_one_or_none() is not None:
        raise UserServiceError(f"username already taken: {username}")

    role = await _get_role_by_name(db, role_name)
    await _validate_group_ids(db, group_ids)

    user = User(username=username, password_hash=hash_password(password), role_id=role.id)
    db.add(user)
    await db.flush()

    for group_id in group_ids:
        db.add(UserGroup(user_id=user.id, group_id=group_id))

    await record_security_event(
        db, SecurityEventType.USER_CREATED, user_id=user.id, metadata={"created_by": str(created_by)}
    )
    await db.flush()
    return user


async def set_active(db: AsyncSession, user: User, *, active: bool, actor_id: uuid.UUID) -> None:
    user.is_active = active
    db.add(user)
    event_type = SecurityEventType.USER_ENABLED if active else SecurityEventType.USER_DISABLED
    await record_security_event(db, event_type, user_id=user.id, metadata={"actor": str(actor_id)})
    await db.flush()


async def lock_account(db: AsyncSession, user: User, *, actor_id: uuid.UUID) -> None:
    """Roadmap B1.10.5 — Account Lock: an admin-triggered equivalent of the
    automatic brute-force login lockout (same Redis mechanism/window as
    `is_login_locked`/`record_login_failure`), distinct from Disable
    (`set_active`, DB-persisted, blocks every request via `get_current_user`)
    — this only blocks new logins, matching what "locked" already means
    elsewhere in this system, and also revokes any session the user
    currently has, so it takes effect immediately.
    """
    await force_login_lock(user.username)
    revoked = await revoke_all_sessions_for_user(user.id)
    await record_security_event(
        db, SecurityEventType.ACCOUNT_LOCKED, user_id=user.id,
        metadata={"actor": str(actor_id), "sessions_revoked": revoked},
    )
    await db.flush()


async def unlock_account(db: AsyncSession, user: User, *, actor_id: uuid.UUID) -> None:
    await clear_login_failures(user.username)
    await record_security_event(
        db, SecurityEventType.ACCOUNT_UNLOCKED, user_id=user.id, metadata={"actor": str(actor_id)}
    )
    await db.flush()


async def get_lockout_status(user: User) -> dict:
    return await get_login_lockout_status(user.username)


async def reset_password(db: AsyncSession, user: User, *, new_password: str, actor_id: uuid.UUID) -> None:
    user.password_hash = hash_password(new_password)
    db.add(user)
    await record_security_event(
        db, SecurityEventType.PASSWORD_RESET_BY_ADMIN, user_id=user.id, metadata={"actor": str(actor_id)}
    )
    await db.flush()


async def change_role(db: AsyncSession, user: User, *, role_name: str, actor_id: uuid.UUID) -> None:
    role = await _get_role_by_name(db, role_name)
    old_role_id = user.role_id
    user.role_id = role.id
    db.add(user)
    await record_security_event(
        db,
        SecurityEventType.USER_ROLE_CHANGED,
        user_id=user.id,
        metadata={"actor": str(actor_id), "old_role_id": str(old_role_id), "new_role": role_name},
    )
    await db.flush()


async def set_groups(db: AsyncSession, user: User, *, group_ids: list[uuid.UUID], actor_id: uuid.UUID) -> None:
    await _validate_group_ids(db, group_ids)
    await db.execute(delete(UserGroup).where(UserGroup.user_id == user.id))
    for group_id in group_ids:
        db.add(UserGroup(user_id=user.id, group_id=group_id))
    await record_security_event(
        db,
        SecurityEventType.USER_GROUPS_CHANGED,
        user_id=user.id,
        metadata={"actor": str(actor_id), "group_ids": [str(g) for g in group_ids]},
    )
    await db.flush()


async def get_group_names(db: AsyncSession, user_id: uuid.UUID) -> list[str]:
    result = await db.execute(
        select(Group.name).join(UserGroup, UserGroup.group_id == Group.id).where(UserGroup.user_id == user_id)
    )
    return [row[0] for row in result.all()]
