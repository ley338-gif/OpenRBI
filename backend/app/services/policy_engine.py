import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.mime_matching import matches_mime_pattern
from app.core.source_matching import matches_source_pattern
from app.models.enums import FileAction, FileRuleType, PolicyVersionStatus
from app.models.group import UserGroup
from app.models.policy import FilePolicyRule, GroupPolicy, Policy, PolicyVersion

# Precedence when multiple applicable group policies disagree
# (docs/policies.md's conflict model) — never relies on group iteration
# order.
_ACTION_PRECEDENCE = {FileAction.DENY: 3, FileAction.QUARANTINE: 2, FileAction.AUTO_RELEASE: 1}


@dataclass
class FileDecisionInput:
    declared_mime: str | None = None
    detected_mime: str | None = None
    extension: str | None = None
    size_bytes: int = 0
    source_hostname: str | None = None


@dataclass
class FileDecisionResult:
    action: FileAction
    policy_version_id: uuid.UUID | None
    matched_rule_id: uuid.UUID | None
    reason: str


async def _published_file_rules_for_user(db: AsyncSession, user_id: uuid.UUID) -> list[tuple[FilePolicyRule, uuid.UUID]]:
    """Every FilePolicyRule belonging to the *currently published* version
    of a policy attached to one of the user's groups. Draft/superseded
    versions never apply — only what's actually live governs a real
    decision (docs/policies.md).
    """
    result = await db.execute(
        select(FilePolicyRule, PolicyVersion.id)
        .join(PolicyVersion, FilePolicyRule.policy_version_id == PolicyVersion.id)
        .join(Policy, PolicyVersion.policy_id == Policy.id)
        .join(GroupPolicy, GroupPolicy.policy_id == Policy.id)
        .join(UserGroup, UserGroup.group_id == GroupPolicy.group_id)
        .where(
            UserGroup.user_id == user_id,
            Policy.current_version_id == PolicyVersion.id,
            PolicyVersion.status == PolicyVersionStatus.PUBLISHED,
        )
    )
    return [(rule, version_id) for rule, version_id in result.all()]


async def evaluate_file_action(
    db: AsyncSession, user_id: uuid.UUID, decision: FileDecisionInput
) -> FileDecisionResult:
    """Fail-closed default (docs/adr/0008): if no published policy rule
    matches at all, the result is QUARANTINE, not AUTO_RELEASE — an
    unmatched/unrecognized case is never silently allowed through.
    """
    rules = await _published_file_rules_for_user(db, user_id)

    best: FileDecisionResult | None = None
    for rule, version_id in rules:
        matched = False
        if rule.rule_type == FileRuleType.MIME:
            matched = (
                matches_mime_pattern(decision.declared_mime, rule.match_pattern)
                or matches_mime_pattern(decision.detected_mime, rule.match_pattern)
                or matches_mime_pattern(decision.extension, rule.match_pattern)
            )
        elif rule.rule_type == FileRuleType.SOURCE:
            matched = bool(decision.source_hostname) and matches_source_pattern(
                decision.source_hostname, rule.match_pattern
            )

        if not matched:
            continue

        candidate = FileDecisionResult(
            action=rule.action,
            policy_version_id=version_id,
            matched_rule_id=rule.id,
            reason=f"matched {rule.rule_type.value} rule '{rule.match_pattern}'",
        )
        if best is None or _ACTION_PRECEDENCE[candidate.action] > _ACTION_PRECEDENCE[best.action]:
            best = candidate

    if best is not None:
        return best

    return FileDecisionResult(
        action=FileAction.QUARANTINE,
        policy_version_id=None,
        matched_rule_id=None,
        reason="no published policy rule matched — fail-closed default",
    )
