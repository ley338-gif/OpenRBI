import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.policies import (
    CreatePolicyRequest,
    CreateVersionRequest,
    FileRuleResponse,
    GroupRef,
    PolicyDetail,
    PolicyListResponse,
    PolicyStats,
    PolicySummary,
    PolicyVersionResponse,
    RollbackRequest,
    UpdatePolicyRequest,
)
from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.group import Group
from app.models.policy import FilePolicyRule, GroupPolicy, Policy, PolicyVersion
from app.models.user import User
from app.services.policies import (
    PolicyServiceError,
    attach_policy_to_group,
    create_draft_version,
    create_policy,
    detach_policy_from_group,
    publish_version,
    rename_policy,
    update_draft_version,
)
from app.services.policies import rollback as rollback_service

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
    versions = (await db.execute(select(PolicyVersion).where(PolicyVersion.policy_id == policy.id))).scalars().all()
    groups = (
        await db.execute(
            select(Group.id, Group.name)
            .join(GroupPolicy, GroupPolicy.group_id == Group.id)
            .where(GroupPolicy.policy_id == policy.id)
            .order_by(Group.name)
        )
    ).all()
    latest = max(versions, key=lambda version: version.created_at, default=None)
    updated_by = None
    if latest and latest.created_by:
        actor = await db.get(User, latest.created_by)
        updated_by = actor.username if actor else None
    updated_at = max([policy.updated_at, *(version.created_at for version in versions)])
    return PolicySummary(
        id=policy.id,
        name=policy.name,
        policy_type=policy.policy_type.value,
        description=policy.description,
        current_version_id=policy.current_version_id,
        current_version_number=current_version_number,
        has_draft=any(version.status.value == "DRAFT" for version in versions),
        version_count=len(versions),
        assigned_groups=[GroupRef(id=group_id, name=group_name) for group_id, group_name in groups],
        created_at=policy.created_at,
        updated_at=updated_at,
        updated_by=updated_by,
    )


@router.get("", response_model=PolicyListResponse)
async def list_policies(
    search: str | None = None,
    policy_type: str | None = None,
    status_filter: str | None = None,
    usage: str | None = None,
    sort_by: str = "updated_at",
    sort_dir: str = "desc",
    offset: int = 0,
    limit: int = 25,
    db: AsyncSession = Depends(get_db),
) -> PolicyListResponse:
    if limit < 1 or limit > 100 or offset < 0:
        raise HTTPException(status_code=422, detail="invalid pagination")
    policies = (await db.execute(select(Policy))).scalars().all()
    summaries = [await _policy_summary(policy, db) for policy in policies]
    stats = PolicyStats(
        total=len(summaries),
        published=sum(item.current_version_id is not None for item in summaries),
        drafts=sum(item.has_draft for item in summaries),
        in_use=sum(bool(item.assigned_groups) for item in summaries),
        total_versions=sum(item.version_count for item in summaries),
        last_updated_at=max((item.updated_at for item in summaries), default=None),
        last_updated_by=max(summaries, key=lambda item: item.updated_at).updated_by if summaries else None,
    )
    filtered = summaries
    if search:
        needle = search.casefold()
        filtered = [item for item in filtered if needle in item.name.casefold() or needle in (item.description or "").casefold()]
    if policy_type:
        filtered = [item for item in filtered if item.policy_type == policy_type]
    if status_filter == "PUBLISHED":
        filtered = [item for item in filtered if item.current_version_id is not None]
    elif status_filter == "DRAFT":
        filtered = [item for item in filtered if item.has_draft]
    if usage == "IN_USE":
        filtered = [item for item in filtered if item.assigned_groups]
    elif usage == "UNASSIGNED":
        filtered = [item for item in filtered if not item.assigned_groups]
    if sort_by not in {"name", "policy_type", "status", "updated_at"} or sort_dir not in {"asc", "desc"}:
        raise HTTPException(status_code=422, detail="invalid sort")
    key = {
        "name": lambda item: item.name.casefold(),
        "policy_type": lambda item: item.policy_type,
        "status": lambda item: (item.current_version_id is not None, item.has_draft),
        "updated_at": lambda item: item.updated_at,
    }[sort_by]
    filtered.sort(key=key, reverse=sort_dir == "desc")
    return PolicyListResponse(items=filtered[offset:offset + limit], total=len(filtered), offset=offset, limit=limit, stats=stats)


@router.post("", response_model=PolicySummary, status_code=status.HTTP_201_CREATED)
async def create_policy_endpoint(
    payload: CreatePolicyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PolicySummary:
    try:
        policy = await create_policy(
            db, name=payload.name, policy_type=payload.policy_type, actor_id=current_user.id, description=payload.description
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


@router.put("/{policy_id}", response_model=PolicySummary)
async def update_policy(
    policy_id: uuid.UUID,
    payload: UpdatePolicyRequest,
    db: AsyncSession = Depends(get_db),
) -> PolicySummary:
    policy = await _get_policy_or_404(db, policy_id)
    try:
        policy = await rename_policy(db, policy, name=payload.name, description=payload.description)
    except PolicyServiceError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(policy)
    return await _policy_summary(policy, db)


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
    # publish_version updates policy.current_version_id, and Policy.updated_at
    # has onupdate=func.now() (TimestampMixin) — a server-computed value the
    # ORM can't know without asking, so it's marked expired after that UPDATE
    # flush. Without this refresh, _policy_summary's synchronous
    # `policy.updated_at` access below tries an implicit lazy reload outside
    # any awaited call, which raises MissingGreenlet in an async session
    # (a real bug, not hypothetical — this endpoint 500'd on every real
    # Publish click until this fix).
    await db.refresh(policy)
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
    # Same reason as the publish endpoint above: rollback_service also
    # updates policy.current_version_id.
    await db.refresh(policy)
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
