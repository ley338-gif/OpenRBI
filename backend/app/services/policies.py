import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import FileAction, FileRuleType, PolicyType, PolicyVersionStatus, SecurityEventType
from app.models.policy import FilePolicyRule, GroupPolicy, Policy, PolicyVersion
from app.services.security_events import record_security_event


class PolicyServiceError(ValueError):
    pass


def _build_file_rules(file_rules: list[dict]) -> list[FilePolicyRule]:
    """Explicitly converts rule_type/action strings to their enum members
    rather than relying on SQLAlchemy to coerce a plain string at flush
    time — fails closed with a clear 400 on a typo'd value instead of an
    obscure DB-layer error.
    """
    built = []
    for rule in file_rules:
        try:
            rule_type = FileRuleType(rule["rule_type"])
            action = FileAction(rule["action"])
        except ValueError as exc:
            raise PolicyServiceError(f"invalid file rule: {exc}") from exc
        built.append(
            FilePolicyRule(
                rule_type=rule_type,
                match_pattern=rule["match_pattern"],
                action=action,
                priority=rule.get("priority", 100),
            )
        )
    return built


async def create_policy(db: AsyncSession, *, name: str, policy_type: str, actor_id: uuid.UUID) -> Policy:
    result = await db.execute(select(Policy).where(Policy.name == name))
    if result.scalar_one_or_none() is not None:
        raise PolicyServiceError(f"policy name already taken: {name}")
    try:
        ptype = PolicyType(policy_type)
    except ValueError as exc:
        raise PolicyServiceError(f"unknown policy type: {policy_type}") from exc

    policy = Policy(name=name, policy_type=ptype)
    db.add(policy)
    await db.flush()
    return policy


async def create_draft_version(
    db: AsyncSession,
    policy: Policy,
    *,
    content: dict,
    file_rules: list[dict],
    actor_id: uuid.UUID,
) -> PolicyVersion:
    result = await db.execute(
        select(PolicyVersion.version_number)
        .where(PolicyVersion.policy_id == policy.id)
        .order_by(PolicyVersion.version_number.desc())
        .limit(1)
    )
    last = result.scalar_one_or_none()
    version = PolicyVersion(
        policy_id=policy.id,
        version_number=(last or 0) + 1,
        status=PolicyVersionStatus.DRAFT,
        content=content,
        created_by=actor_id,
    )
    db.add(version)
    await db.flush()

    for rule in _build_file_rules(file_rules):
        rule.policy_version_id = version.id
        db.add(rule)
    await db.flush()
    return version


async def update_draft_version(
    db: AsyncSession, version: PolicyVersion, *, content: dict, file_rules: list[dict]
) -> PolicyVersion:
    """A published version is immutable (docs/policies.md) — editing always
    means creating a new draft (create_draft_version), never mutating one
    that's already live or was ever live.
    """
    if version.status != PolicyVersionStatus.DRAFT:
        raise PolicyServiceError(f"cannot edit a version in status {version.status.value}, it is not a draft")

    built_rules = _build_file_rules(file_rules)  # validate before mutating anything
    version.content = content
    db.add(version)
    await db.execute(delete(FilePolicyRule).where(FilePolicyRule.policy_version_id == version.id))
    for rule in built_rules:
        rule.policy_version_id = version.id
        db.add(rule)
    await db.flush()
    return version


async def publish_version(
    db: AsyncSession, policy: Policy, version: PolicyVersion, *, actor_id: uuid.UUID
) -> None:
    if version.policy_id != policy.id:
        raise PolicyServiceError("version does not belong to this policy")
    if version.status != PolicyVersionStatus.DRAFT:
        raise PolicyServiceError(f"cannot publish a version in status {version.status.value}")

    if policy.current_version_id is not None:
        previous = await db.get(PolicyVersion, policy.current_version_id)
        if previous is not None:
            previous.status = PolicyVersionStatus.SUPERSEDED
            db.add(previous)

    version.status = PolicyVersionStatus.PUBLISHED
    version.published_at = datetime.now(UTC)
    db.add(version)
    policy.current_version_id = version.id
    db.add(policy)

    await record_security_event(
        db,
        SecurityEventType.POLICY_PUBLISHED,
        user_id=actor_id,
        metadata={"policy_id": str(policy.id), "policy_version_id": str(version.id)},
    )
    await db.flush()


async def rollback(db: AsyncSession, policy: Policy, target_version: PolicyVersion, *, actor_id: uuid.UUID) -> None:
    """Re-activates a version that was published at some point in the past
    (docs/policies.md's "Rollback ermöglichen"). A version that was never
    published (still DRAFT) is not a valid rollback target — use publish
    for that instead.
    """
    if target_version.policy_id != policy.id:
        raise PolicyServiceError("version does not belong to this policy")
    if target_version.status not in (PolicyVersionStatus.PUBLISHED, PolicyVersionStatus.SUPERSEDED):
        raise PolicyServiceError(f"cannot roll back to a version in status {target_version.status.value}")
    if policy.current_version_id == target_version.id:
        raise PolicyServiceError("target version is already current")

    if policy.current_version_id is not None:
        current = await db.get(PolicyVersion, policy.current_version_id)
        if current is not None:
            current.status = PolicyVersionStatus.SUPERSEDED
            db.add(current)

    target_version.status = PolicyVersionStatus.PUBLISHED
    db.add(target_version)
    policy.current_version_id = target_version.id
    db.add(policy)

    await record_security_event(
        db,
        SecurityEventType.POLICY_CHANGED,
        user_id=actor_id,
        metadata={"policy_id": str(policy.id), "rolled_back_to_version_id": str(target_version.id)},
    )
    await db.flush()


async def attach_policy_to_group(db: AsyncSession, *, group_id: uuid.UUID, policy_id: uuid.UUID) -> None:
    result = await db.execute(
        select(GroupPolicy).where(GroupPolicy.group_id == group_id, GroupPolicy.policy_id == policy_id)
    )
    if result.scalar_one_or_none() is not None:
        return  # idempotent
    db.add(GroupPolicy(group_id=group_id, policy_id=policy_id))
    await db.flush()


async def detach_policy_from_group(db: AsyncSession, *, group_id: uuid.UUID, policy_id: uuid.UUID) -> None:
    await db.execute(
        delete(GroupPolicy).where(GroupPolicy.group_id == group_id, GroupPolicy.policy_id == policy_id)
    )
    await db.flush()
