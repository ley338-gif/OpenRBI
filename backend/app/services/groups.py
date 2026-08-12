import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import SecurityEventType
from app.models.group import Group, UserGroup
from app.services.security_events import record_security_event


class GroupServiceError(ValueError):
    pass


async def create_group(db: AsyncSession, *, name: str, description: str | None, actor_id: uuid.UUID) -> Group:
    result = await db.execute(select(Group).where(Group.name == name))
    if result.scalar_one_or_none() is not None:
        raise GroupServiceError(f"group name already taken: {name}")

    group = Group(name=name, description=description)
    db.add(group)
    await db.flush()
    await record_security_event(
        db, SecurityEventType.GROUP_CREATED, metadata={"actor": str(actor_id), "group_id": str(group.id)}
    )
    await db.flush()
    return group


async def list_groups_with_member_counts(db: AsyncSession) -> list[tuple[Group, int]]:
    result = await db.execute(
        select(Group, func.count(UserGroup.id))
        .outerjoin(UserGroup, UserGroup.group_id == Group.id)
        .group_by(Group.id)
        .order_by(Group.name)
    )
    return list(result.all())
