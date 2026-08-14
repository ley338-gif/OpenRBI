"""Policy-engine checklist items: MIME DENY rules work, unknown file types
fail closed to QUARANTINE, forged-domain source rules do not match, and
conflicting group policies resolve deterministically (DENY > QUARANTINE >
AUTO_RELEASE).
"""
import uuid

import pytest
from sqlalchemy import select

from app.core.source_matching import matches_source_pattern
from app.models.enums import SecurityEventType
from app.models.group import Group, UserGroup
from app.models.security_event import SecurityEvent
from app.services.policies import (
    attach_policy_to_group,
    create_draft_version,
    create_policy,
    publish_version,
    rollback,
)
from app.services.policy_engine import (
    DEFAULT_SCREEN_HEIGHT,
    DEFAULT_SCREEN_WIDTH,
    FileDecisionInput,
    evaluate_file_action,
    resolve_session_resolution,
)

from tests.conftest import PREFIX, make_user


async def _make_group(db) -> Group:
    group = Group(name=f"{PREFIX}group_{uuid.uuid4().hex[:8]}")
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return group


async def _make_published_mime_policy(db, *, actor_id, action: str, pattern: str = "application/x-msdownload"):
    policy = await create_policy(db, name=f"{PREFIX}policy_{uuid.uuid4().hex[:8]}", policy_type="MIME", actor_id=actor_id)
    version = await create_draft_version(
        db,
        policy,
        content={},
        file_rules=[{"rule_type": "MIME", "match_pattern": pattern, "action": action}],
        actor_id=actor_id,
    )
    await publish_version(db, policy, version, actor_id=actor_id)
    await db.commit()
    return policy


async def _make_published_session_policy(db, *, actor_id, content: dict):
    policy = await create_policy(db, name=f"{PREFIX}policy_{uuid.uuid4().hex[:8]}", policy_type="SESSION", actor_id=actor_id)
    version = await create_draft_version(db, policy, content=content, file_rules=[], actor_id=actor_id)
    await publish_version(db, policy, version, actor_id=actor_id)
    await db.commit()
    return policy


@pytest.mark.parametrize(
    "hostname,pattern,should_match",
    [
        ("download.microsoft.com", "*.microsoft.com", True),
        ("microsoft.com", "*.microsoft.com", True),  # bare apex matches its own *.-wildcard too
        ("microsoft.com.attacker.org", "*.microsoft.com", False),
        ("evil-microsoft.com", "*.microsoft.com", False),
        ("office.microsoft.com", "*.microsoft.com", True),
    ],
)
def test_source_matching_rejects_forged_domains(hostname, pattern, should_match):
    assert matches_source_pattern(hostname, pattern) is should_match


@pytest.mark.asyncio
async def test_unmatched_file_fails_closed_to_quarantine(db):
    user, _ = await make_user(db, role_name="USER")
    result = await evaluate_file_action(
        db, user.id, FileDecisionInput(declared_mime="application/x-totally-unknown-type")
    )
    assert result.action.value == "QUARANTINE"
    assert result.matched_rule_id is None


@pytest.mark.asyncio
async def test_mime_deny_rule_blocks_matching_file(db):
    user, _ = await make_user(db, role_name="USER")
    group = await _make_group(db)
    db.add(UserGroup(user_id=user.id, group_id=group.id))
    await db.commit()

    policy = await _make_published_mime_policy(db, actor_id=user.id, action="DENY")
    await attach_policy_to_group(db, group_id=group.id, policy_id=policy.id)

    result = await evaluate_file_action(
        db, user.id, FileDecisionInput(declared_mime="application/x-msdownload")
    )
    assert result.action.value == "DENY"
    assert result.matched_rule_id is not None


@pytest.mark.asyncio
async def test_conflicting_group_policies_resolve_to_most_restrictive(db):
    """Two groups on the same user, one AUTO_RELEASE and one DENY for the
    same file type — the deterministic conflict model (docs/policies.md)
    must resolve to DENY, never AUTO_RELEASE, regardless of which group's
    policy happens to be evaluated first.
    """
    user, _ = await make_user(db, role_name="USER")
    permissive_group = await _make_group(db)
    strict_group = await _make_group(db)
    db.add_all([
        UserGroup(user_id=user.id, group_id=permissive_group.id),
        UserGroup(user_id=user.id, group_id=strict_group.id),
    ])
    await db.commit()

    permissive_policy = await _make_published_mime_policy(db, actor_id=user.id, action="AUTO_RELEASE")
    strict_policy = await _make_published_mime_policy(db, actor_id=user.id, action="DENY")
    await attach_policy_to_group(db, group_id=permissive_group.id, policy_id=permissive_policy.id)
    await attach_policy_to_group(db, group_id=strict_group.id, policy_id=strict_policy.id)

    result = await evaluate_file_action(
        db, user.id, FileDecisionInput(declared_mime="application/x-msdownload")
    )
    assert result.action.value == "DENY"


@pytest.mark.asyncio
async def test_pdf_auto_release_alone_is_released(db):
    """Reported-bug repro, step 1: a user in exactly one group with a
    published application/pdf -> AUTO_RELEASE rule and nothing else must
    get AUTO_RELEASE for a PDF. Isolates whether the core MIME-match path
    itself is broken.
    """
    user, _ = await make_user(db, role_name="USER")
    group = await _make_group(db)
    db.add(UserGroup(user_id=user.id, group_id=group.id))
    await db.commit()

    policy = await _make_published_mime_policy(
        db, actor_id=user.id, action="AUTO_RELEASE", pattern="application/pdf"
    )
    await attach_policy_to_group(db, group_id=group.id, policy_id=policy.id)

    result = await evaluate_file_action(db, user.id, FileDecisionInput(detected_mime="application/pdf"))
    assert result.action.value == "AUTO_RELEASE"
    assert result.matched_rule_id is not None


@pytest.mark.asyncio
async def test_pdf_auto_release_overridden_by_broader_quarantine_rule_in_second_group(db):
    """Reported-bug repro, step 2: same user additionally belongs to a
    second, realistic group with a broader application/* -> QUARANTINE
    rule. Per the documented conflict model (docs/policies.md), QUARANTINE
    beats AUTO_RELEASE regardless of which rule is more specific — this is
    the deliberately conservative precedence, not a bug.
    """
    user, _ = await make_user(db, role_name="USER")
    pdf_group = await _make_group(db)
    default_group = await _make_group(db)
    db.add_all([
        UserGroup(user_id=user.id, group_id=pdf_group.id),
        UserGroup(user_id=user.id, group_id=default_group.id),
    ])
    await db.commit()

    pdf_policy = await _make_published_mime_policy(
        db, actor_id=user.id, action="AUTO_RELEASE", pattern="application/pdf"
    )
    default_policy = await _make_published_mime_policy(
        db, actor_id=user.id, action="QUARANTINE", pattern="application/*"
    )
    await attach_policy_to_group(db, group_id=pdf_group.id, policy_id=pdf_policy.id)
    await attach_policy_to_group(db, group_id=default_group.id, policy_id=default_policy.id)

    result = await evaluate_file_action(db, user.id, FileDecisionInput(detected_mime="application/pdf"))
    assert result.action.value == "QUARANTINE"


@pytest.mark.asyncio
async def test_publish_and_rollback_generate_audit_events(db):
    actor, _ = await make_user(db, role_name="USER")
    actor_id = actor.id
    policy = await create_policy(
        db, name=f"{PREFIX}policy_{uuid.uuid4().hex[:8]}", policy_type="MIME", actor_id=actor_id
    )
    v1 = await create_draft_version(db, policy, content={}, file_rules=[], actor_id=actor_id)
    await publish_version(db, policy, v1, actor_id=actor_id)
    await db.commit()

    result = await db.execute(
        select(SecurityEvent).where(
            SecurityEvent.event_type == SecurityEventType.POLICY_PUBLISHED,
            SecurityEvent.metadata_json["policy_id"].astext == str(policy.id),
        )
    )
    assert result.scalars().first() is not None

    v2 = await create_draft_version(db, policy, content={}, file_rules=[], actor_id=actor_id)
    await publish_version(db, policy, v2, actor_id=actor_id)
    await db.commit()

    await rollback(db, policy, v1, actor_id=actor_id)
    await db.commit()

    result = await db.execute(
        select(SecurityEvent).where(
            SecurityEvent.event_type == SecurityEventType.POLICY_CHANGED,
            SecurityEvent.metadata_json["rolled_back_to_version_id"].astext == str(v1.id),
        )
    )
    assert result.scalars().first() is not None


@pytest.mark.asyncio
async def test_session_resolution_falls_back_to_default_with_no_policy(db):
    user, _ = await make_user(db, role_name="USER")
    resolution = await resolve_session_resolution(db, user.id)
    assert resolution.width == DEFAULT_SCREEN_WIDTH
    assert resolution.height == DEFAULT_SCREEN_HEIGHT


@pytest.mark.asyncio
async def test_session_resolution_reads_published_session_policy(db):
    user, _ = await make_user(db, role_name="USER")
    group = await _make_group(db)
    db.add(UserGroup(user_id=user.id, group_id=group.id))
    await db.commit()

    policy = await _make_published_session_policy(
        db, actor_id=user.id, content={"screen_width": 1920, "screen_height": 1080}
    )
    await attach_policy_to_group(db, group_id=group.id, policy_id=policy.id)

    resolution = await resolve_session_resolution(db, user.id)
    assert resolution.width == 1920
    assert resolution.height == 1080


@pytest.mark.asyncio
async def test_session_resolution_ignores_malformed_content(db):
    """A policy published with no resolution set (content={}), or with a
    non-numeric value someone hand-edited in, must never break session
    creation — it's silently skipped, falling back to the default exactly
    as if the policy didn't exist.
    """
    user, _ = await make_user(db, role_name="USER")
    group = await _make_group(db)
    db.add(UserGroup(user_id=user.id, group_id=group.id))
    await db.commit()

    policy = await _make_published_session_policy(db, actor_id=user.id, content={"screen_width": "not-a-number"})
    await attach_policy_to_group(db, group_id=group.id, policy_id=policy.id)

    resolution = await resolve_session_resolution(db, user.id)
    assert resolution.width == DEFAULT_SCREEN_WIDTH
    assert resolution.height == DEFAULT_SCREEN_HEIGHT


@pytest.mark.asyncio
async def test_session_resolution_conflict_picks_smallest_area(db):
    """Two groups on the same user disagree on resolution — the smaller
    pixel area wins (docs/policies.md's conflict model for SESSION
    policies), regardless of which group's policy is evaluated first.
    """
    user, _ = await make_user(db, role_name="USER")
    large_group = await _make_group(db)
    small_group = await _make_group(db)
    db.add_all([
        UserGroup(user_id=user.id, group_id=large_group.id),
        UserGroup(user_id=user.id, group_id=small_group.id),
    ])
    await db.commit()

    large_policy = await _make_published_session_policy(
        db, actor_id=user.id, content={"screen_width": 1920, "screen_height": 1080}
    )
    small_policy = await _make_published_session_policy(
        db, actor_id=user.id, content={"screen_width": 1024, "screen_height": 768}
    )
    await attach_policy_to_group(db, group_id=large_group.id, policy_id=large_policy.id)
    await attach_policy_to_group(db, group_id=small_group.id, policy_id=small_policy.id)

    resolution = await resolve_session_resolution(db, user.id)
    assert resolution.width == 1024
    assert resolution.height == 768


@pytest.mark.asyncio
async def test_create_session_applies_resolved_policy_resolution(db):
    """End-to-end through the real create_session orchestration (against the
    real, already-running Session Agent — never mocked, matching this
    suite's convention): the BrowserSession row created for a user in a
    group with a published SESSION policy carries that policy's resolution,
    not the sandbox default.
    """
    from app.services.sessions import create_session as create_session_service

    user, _ = await make_user(db, role_name="USER")
    group = await _make_group(db)
    db.add(UserGroup(user_id=user.id, group_id=group.id))
    await db.commit()

    policy = await _make_published_session_policy(
        db, actor_id=user.id, content={"screen_width": 1024, "screen_height": 768}
    )
    await attach_policy_to_group(db, group_id=group.id, policy_id=policy.id)

    session = await create_session_service(db, user)
    await db.commit()

    assert session.screen_width == 1024
    assert session.screen_height == 768
