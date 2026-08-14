import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.mime_matching import matches_mime_pattern
from app.core.source_matching import matches_source_pattern
from app.models.enums import (
    ClipboardMode,
    FileAction,
    FileRuleType,
    PolicyType,
    PolicyVersionStatus,
)
from app.models.group import UserGroup
from app.models.policy import FilePolicyRule, GroupPolicy, Policy, PolicyVersion

# Precedence when multiple applicable group policies disagree
# (docs/policies.md's conflict model) — never relies on group iteration
# order.
_ACTION_PRECEDENCE = {FileAction.DENY: 3, FileAction.QUARANTINE: 2, FileAction.AUTO_RELEASE: 1}

# Same conservative "any group that wants it locked down wins" precedence
# as _ACTION_PRECEDENCE above, applied per clipboard *direction* rather
# than to the four ClipboardMode values directly: a group's policy blocks
# LOCAL_TO_REMOTE if its mode isn't LOCAL_TO_REMOTE or BIDIRECTIONAL_TEXT,
# and blocks REMOTE_TO_LOCAL if its mode isn't REMOTE_TO_LOCAL or
# BIDIRECTIONAL_TEXT. The resolved mode allows a direction only if every
# applicable policy allows it — one group's NONE beats another group's
# BIDIRECTIONAL_TEXT, and (the case _ACTION_PRECEDENCE-style single-tier
# ranking can't express) one group's LOCAL_TO_REMOTE-only and another's
# REMOTE_TO_LOCAL-only combine to NONE, not to an arbitrary pick of one
# direction — consistent with the project's fail-closed default: two
# groups that only agree the *other* direction should be blocked never
# resolves to "the union of what each individually allowed" in this
# engine (see _ACTION_PRECEDENCE above, same principle for file actions).
_ALLOWS_LOCAL_TO_REMOTE = {ClipboardMode.LOCAL_TO_REMOTE, ClipboardMode.BIDIRECTIONAL_TEXT}
_ALLOWS_REMOTE_TO_LOCAL = {ClipboardMode.REMOTE_TO_LOCAL, ClipboardMode.BIDIRECTIONAL_TEXT}

# Used whenever no applicable CLIPBOARD policy sets a mode — an
# installation with no CLIPBOARD policies configured behaves exactly as it
# did before this feature existed (unrestricted, both directions).
DEFAULT_CLIPBOARD_MODE = ClipboardMode.BIDIRECTIONAL_TEXT

# Used whenever no applicable SESSION policy sets a resolution — matches
# the sandbox image's own long-standing defaults (docker/browser/
# entrypoint.sh), so an installation with no SESSION policies configured at
# all behaves exactly as it did before this feature existed.
DEFAULT_SCREEN_WIDTH = 1280
DEFAULT_SCREEN_HEIGHT = 800


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


@dataclass
class SessionResolution:
    width: int
    height: int


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


async def resolve_session_resolution(db: AsyncSession, user_id: uuid.UUID) -> SessionResolution:
    """Reads screen_width/screen_height out of the published SESSION-type
    policies attached to the user's groups. Falls back to the sandbox's own
    defaults when no policy sets a resolution, or when a policy's `content`
    doesn't carry valid values at all — a malformed policy content field
    never blocks session creation.

    Multiple applicable SESSION policies can disagree, the same way
    multiple file-rule policies can (see _ACTION_PRECEDENCE above); there's
    no natural "more restrictive" resolution, so the smallest pixel area
    wins — consistent with this app's general conservative precedence when
    policies conflict, and it never spends more of a node's resources than
    any single applicable policy asked for.
    """
    result = await db.execute(
        select(PolicyVersion.content)
        .join(Policy, PolicyVersion.policy_id == Policy.id)
        .join(GroupPolicy, GroupPolicy.policy_id == Policy.id)
        .join(UserGroup, UserGroup.group_id == GroupPolicy.group_id)
        .where(
            UserGroup.user_id == user_id,
            Policy.policy_type == PolicyType.SESSION,
            Policy.current_version_id == PolicyVersion.id,
            PolicyVersion.status == PolicyVersionStatus.PUBLISHED,
        )
    )

    best: SessionResolution | None = None
    for (content,) in result.all():
        if not isinstance(content, dict):
            continue
        width = content.get("screen_width")
        height = content.get("screen_height")
        if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
            continue
        if best is None or width * height < best.width * best.height:
            best = SessionResolution(width=width, height=height)

    if best is not None:
        return best
    return SessionResolution(width=DEFAULT_SCREEN_WIDTH, height=DEFAULT_SCREEN_HEIGHT)


async def resolve_clipboard_policy(db: AsyncSession, user_id: uuid.UUID) -> ClipboardMode:
    """Reads the clipboard mode out of the published CLIPBOARD-type
    policies attached to the user's groups, structurally the same query
    shape as resolve_session_resolution above. A policy's `content` is
    expected to carry {"clipboard_mode": "<one of the four enum values>"};
    a missing/unrecognized value is silently skipped (fail-open per-policy,
    matching resolve_session_resolution's own handling of malformed
    content) rather than blocking session creation over a typo.

    See _ALLOWS_LOCAL_TO_REMOTE/_ALLOWS_REMOTE_TO_LOCAL above for the
    conflict model: a direction is only in the resolved mode if every
    applicable policy allows it.
    """
    result = await db.execute(
        select(PolicyVersion.content)
        .join(Policy, PolicyVersion.policy_id == Policy.id)
        .join(GroupPolicy, GroupPolicy.policy_id == Policy.id)
        .join(UserGroup, UserGroup.group_id == GroupPolicy.group_id)
        .where(
            UserGroup.user_id == user_id,
            Policy.policy_type == PolicyType.CLIPBOARD,
            Policy.current_version_id == PolicyVersion.id,
            PolicyVersion.status == PolicyVersionStatus.PUBLISHED,
        )
    )

    modes: list[ClipboardMode] = []
    for (content,) in result.all():
        if not isinstance(content, dict):
            continue
        raw = content.get("clipboard_mode")
        try:
            modes.append(ClipboardMode(raw))
        except ValueError:
            continue

    if not modes:
        return DEFAULT_CLIPBOARD_MODE

    allow_local_to_remote = all(mode in _ALLOWS_LOCAL_TO_REMOTE for mode in modes)
    allow_remote_to_local = all(mode in _ALLOWS_REMOTE_TO_LOCAL for mode in modes)

    if allow_local_to_remote and allow_remote_to_local:
        return ClipboardMode.BIDIRECTIONAL_TEXT
    if allow_local_to_remote:
        return ClipboardMode.LOCAL_TO_REMOTE
    if allow_remote_to_local:
        return ClipboardMode.REMOTE_TO_LOCAL
    return ClipboardMode.NONE
