import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.policies import (
    CreatePolicyRequest,
    CreateVersionRequest,
    FileRuleResponse,
    PolicyDetail,
    PolicySummary,
    PolicyVersionResponse,
    RollbackRequest,
)
from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.policy import FilePolicyRule, Policy, PolicyVersion
from app.models.user import User
from app.services.policies import (
    PolicyServiceError,
    attach_policy_to_group,
    create_draft_version,
    create_policy,
    detach_policy_from_group,
    publish_version,
    rollback as rollback_service,
    update_draft_version,
)

router = APIRouter(prefix="/admin/policies", tags=["admin"], dependencies=[Depends(require_role("ADMIN"))])


async def _get_policy_or_404(db: AsyncSession, policy_id: uuid.UUID) -> Policy:
    policy = await db.get(Policy, policy_id)
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="policy not found")
    return policy


async def _get_version_or_404(db: AsyncSession, version_id: uuid.UUID) -> PolicyVersion:
    version = await db.get(PolicyVersion, version_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="policy version not found")
    return version


async def _version_response(db: AsyncSession, version: PolicyVersion) -> PolicyVersionResponse:
    result = await db.execute(
        select(FilePolicyRule)
        .where(FilePolicyRule.policy_version_id == version.id)
        .order_by(FilePolicyRule.priority)
    )
    rules = [
        FileRuleResponse(
            id=r.id, rule_type=r.rule_type.value, match_pattern=r.match_pattern, action=r.action.value,
            priority=r.priority,
        )
        for r in result.scalars()
    ]
    return PolicyVersionResponse(
        id=version.id,
        version_number=version.version_number,
        status=version.status.value,
        content=version.content,
        file_rules=rules,
        created_at=version.created_at,
        published_at=version.published_at,
    )


async def _policy_summary(policy: Policy, db: AsyncSession) -> PolicySummary:
    current_version_number = None
    if policy.current_version_id is not None:
        current = await db.get(PolicyVersion, policy.current_version_id)
        current_version_number = current.version_number if current else None
    return PolicySummary(
        id=policy.id,
        name=policy.name,
        policy_type=policy.policy_type.value,
        description=policy.description,
        current_version_id=policy.current_version_id,
        current_version_number=current_version_number,
    )


@router.get("", response_model=list[PolicySummary])
async def list_policies(db: AsyncSession = Depends(get_db)) -> list[PolicySummary]:
    result = await db.execute(select(Policy).order_by(Policy.name))
    return [await _policy_summary(p, db) for p in result.scalars()]


@router.post("", response_model=PolicySummary, status_code=status.HTTP_201_CREATED)
async def create_policy_endpoint(
    payload: CreatePolicyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PolicySummary:
    try:
        policy = await create_policy(
            db, name=payload.name, policy_type=payload.policy_type, actor_id=current_user.id
        )
    except PolicyServiceError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return await _policy_summary(policy, db)


@router.get("/{policy_id}", response_model=PolicyDetail)
async def get_policy(policy_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> PolicyDetail:
    policy = await _get_policy_or_404(db, policy_id)
    result = await db.execute(
        select(PolicyVersion).where(PolicyVersion.policy_id == policy.id).order_by(PolicyVersion.version_number)
    )
    versions = [await _version_response(db, v) for v in result.scalars()]
    summary = await _policy_summary(policy, db)
    return PolicyDetail(**summary.model_dump(), versions=versions)


@router.post("/{policy_id}/versions", response_model=PolicyVersionResponse, status_code=status.HTTP_201_CREATED)
async def create_version(
    policy_id: uuid.UUID,
    payload: CreateVersionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PolicyVersionResponse:
    policy = await _get_policy_or_404(db, policy_id)
    version = await create_draft_version(
        db,
        policy,
        content=payload.content,
        file_rules=[r.model_dump() for r in payload.file_rules],
        actor_id=current_user.id,
    )
    await db.commit()
    return await _version_response(db, version)


@router.put("/{policy_id}/versions/{version_id}", response_model=PolicyVersionResponse)
async def update_version(
    policy_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: CreateVersionRequest,
    db: AsyncSession = Depends(get_db),
) -> PolicyVersionResponse:
    await _get_policy_or_404(db, policy_id)
    version = await _get_version_or_404(db, version_id)
    try:
        version = await update_draft_version(
            db, version, content=payload.content, file_rules=[r.model_dump() for r in payload.file_rules]
        )
    except PolicyServiceError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    return await _version_response(db, version)


@router.post("/{policy_id}/versions/{version_id}/publish", response_model=PolicyDetail)
async def publish(
    policy_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PolicyDetail:
    policy = await _get_policy_or_404(db, policy_id)
    version = await _get_version_or_404(db, version_id)
    try:
        await publish_version(db, policy, version, actor_id=current_user.id)
    except PolicyServiceError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    result = await db.execute(
        select(PolicyVersion).where(PolicyVersion.policy_id == policy.id).order_by(PolicyVersion.version_number)
    )
    versions = [await _version_response(db, v) for v in result.scalars()]
    summary = await _policy_summary(policy, db)
    return PolicyDetail(**summary.model_dump(), versions=versions)


@router.post("/{policy_id}/rollback", response_model=PolicySummary)
async def rollback_endpoint(
    policy_id: uuid.UUID,
    payload: RollbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PolicySummary:
    policy = await _get_policy_or_404(db, policy_id)
    target = await _get_version_or_404(db, payload.version_id)
    try:
        await rollback_service(db, policy, target, actor_id=current_user.id)
    except PolicyServiceError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    return await _policy_summary(policy, db)


@router.post("/{policy_id}/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def attach_to_group(policy_id: uuid.UUID, group_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    await _get_policy_or_404(db, policy_id)
    await attach_policy_to_group(db, group_id=group_id, policy_id=policy_id)
    await db.commit()


@router.delete("/{policy_id}/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def detach_from_group(policy_id: uuid.UUID, group_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    await _get_policy_or_404(db, policy_id)
    await detach_policy_from_group(db, group_id=group_id, policy_id=policy_id)
    await db.commit()
