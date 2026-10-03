"""ADR 0025 regression: the openrbi_user/openrbi_admin Postgres roles that
scripts/provision-segmented-db-roles.sh creates must be able to run what
their listener actually does — not only be refused what they must not do
(scripts/test-segmented-credential-scoping.sh covers that half).

Runs the real service functions under each role, inside a transaction
that is rolled back, so nothing persists. Skipped unless the roles exist
and OPENRBI_DB_USER_ROLE_PASSWORD/OPENRBI_DB_ADMIN_ROLE_PASSWORD are set
(CI's backend-integration-tests job provisions them).
"""
import os
import types
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.browser_node import BrowserNode
from app.models.browser_session import BrowserSession
from app.models.enums import SecurityEventType, SessionStatus
from app.models.group import Group, UserGroup
from app.models.policy import PolicyVersion
from app.models.user import User
from app.services import groups as groups_service
from app.services import ldap_config_service
from app.services import mfa as mfa_service
from app.services import policies as policies_service
from app.services.incidents import check_repeated_policy_violations
from app.services.metrics_history import record_sample
from app.services.policy_engine import (
    FileDecisionInput,
    evaluate_file_action,
    resolve_clipboard_policy,
    resolve_session_resolution,
)
from app.services.security_events import record_security_event
from app.services.sessions import _apply_node_status
from tests.conftest import PREFIX, make_user

USER_PW = os.environ.get("OPENRBI_DB_USER_ROLE_PASSWORD")
ADMIN_PW = os.environ.get("OPENRBI_DB_ADMIN_ROLE_PASSWORD")

pytestmark = pytest.mark.skipif(
    not (USER_PW and ADMIN_PW),
    reason="Segmented DB roles not provisioned (scripts/provision-segmented-db-roles.sh)",
)


@pytest_asyncio.fixture
async def roles(db):
    exists = await db.scalar(text("SELECT count(*) FROM pg_roles WHERE rolname IN ('openrbi_user', 'openrbi_admin')"))
    if exists != 2:
        pytest.skip("openrbi_user/openrbi_admin roles do not exist in this database")
    base = make_url(get_settings().database_url)
    engines = {
        "user": create_async_engine(base.set(username="openrbi_user", password=USER_PW)),
        "admin": create_async_engine(base.set(username="openrbi_admin", password=ADMIN_PW)),
    }
    yield {name: async_sessionmaker(engine, expire_on_commit=False) for name, engine in engines.items()}
    for engine in engines.values():
        await engine.dispose()


async def _any_node(db) -> BrowserNode:
    node = (await db.execute(select(BrowserNode).limit(1))).scalar_one_or_none()
    if node is None:
        pytest.skip("no browser node registered yet")
    return node


async def _user_with_published_policy(db):
    admin, _ = await make_user(db, role_name="ADMIN")
    user, _ = await make_user(db, role_name="USER")
    group = Group(name=f"{PREFIX}group_{uuid.uuid4().hex[:8]}")
    db.add(group)
    await db.flush()
    db.add(UserGroup(user_id=user.id, group_id=group.id))
    policy = await policies_service.create_policy(db, name=f"{PREFIX}policy_{uuid.uuid4().hex[:8]}", policy_type="MIME", actor_id=admin.id)
    version = await policies_service.create_draft_version(
        db, policy, content={}, file_rules=[{"rule_type": "MIME", "match_pattern": "application/pdf", "action": "QUARANTINE"}],
        actor_id=admin.id,
    )
    await policies_service.publish_version(db, policy, version, actor_id=admin.id)
    await policies_service.attach_policy_to_group(db, group_id=group.id, policy_id=policy.id)
    draft = await policies_service.create_draft_version(db, policy, content={}, file_rules=[], actor_id=admin.id)
    await db.commit()
    return admin, user, group, policy, draft


@pytest.mark.asyncio
async def test_user_role_can_start_a_session(db, roles):
    _, user, _, _, _ = await _user_with_published_policy(db)
    async with roles["user"]() as scoped:
        node = await _any_node(scoped)
        # What select_node() does with each candidate's fresh self-report.
        _apply_node_status(node, types.SimpleNamespace(
            status=node.status.value, capacity=node.capacity, capacity_bound=node.capacity_bound,
            ram_capacity=node.ram_capacity, cpu_capacity=node.cpu_capacity, active_sessions=node.active_sessions,
            runtime=node.runtime, version=node.version, cpu_percent=node.cpu_percent, ram_total_mb=node.ram_total_mb,
            ram_used_mb=node.ram_used_mb, node_started_at=node.node_started_at,
        ))
        await scoped.flush()
        await resolve_session_resolution(scoped, user.id)
        await resolve_clipboard_policy(scoped, user.id)
        scoped.add(BrowserSession(user_id=user.id, node_id=node.id, status=SessionStatus.QUEUED))
        await scoped.flush()
        await record_security_event(scoped, SecurityEventType.SESSION_STARTED, user_id=user.id)
        await scoped.flush()
        await scoped.rollback()


@pytest.mark.asyncio
async def test_user_role_can_evaluate_files_and_open_incidents(db, roles):
    _, user, _, _, _ = await _user_with_published_policy(db)
    for _ in range(3):
        await record_security_event(db, SecurityEventType.UPLOAD_BLOCKED, user_id=user.id)
    await db.commit()
    async with roles["user"]() as scoped:
        result = await evaluate_file_action(scoped, user.id, FileDecisionInput(detected_mime="application/pdf"))
        assert result.action.value == "QUARANTINE"
        assert result.matched_rule_id is not None
        await check_repeated_policy_violations(scoped, user.id)  # crosses the threshold, inserts an incident
        await scoped.flush()
        await scoped.rollback()


@pytest.mark.asyncio
async def test_scoped_user_listener_never_reads_ldap_config(roles, monkeypatch):
    scoped_settings = get_settings().model_copy(
        update={"listener_mode": "user", "database_url_user": "postgresql+asyncpg://openrbi_user@postgres/openrbi"}
    )
    monkeypatch.setattr(ldap_config_service, "get_settings", lambda: scoped_settings)
    async with roles["user"]() as scoped:
        assert await ldap_config_service.get_effective_ldap_config(scoped) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        "SELECT * FROM ldap_configs",
        "UPDATE users SET role_id = role_id WHERE id IS NULL",
        "INSERT INTO users (id, username, role_id) SELECT gen_random_uuid(), 'x', role_id FROM users WHERE id IS NULL",
        "SELECT metadata_json FROM security_events WHERE id IS NULL",
        "UPDATE browser_nodes SET endpoint_url = endpoint_url WHERE id IS NULL",
        "UPDATE browser_nodes SET agent_token_encrypted = agent_token_encrypted WHERE id IS NULL",
        "UPDATE browser_nodes SET enrollment_status = enrollment_status WHERE id IS NULL",
        "UPDATE policies SET name = name WHERE id IS NULL",
        "SELECT description FROM incidents WHERE id IS NULL",
        "DELETE FROM security_events WHERE id IS NULL",
    ],
)
async def test_user_role_is_still_refused_what_it_must_not_do(roles, statement):
    async with roles["user"]() as scoped:
        with pytest.raises(DBAPIError, match="permission denied"):
            await scoped.execute(text(statement))


@pytest.mark.asyncio
async def test_admin_role_can_run_admin_deletes(db, roles):
    admin, user, group, policy, draft = await _user_with_published_policy(db)
    async with roles["admin"]() as scoped:
        await policies_service.update_draft_version(
            scoped, await scoped.get(PolicyVersion, draft.id), content={},
            file_rules=[{"rule_type": "MIME", "match_pattern": "image/*", "action": "QUARANTINE"}],
        )
        await policies_service.detach_policy_from_group(scoped, group_id=group.id, policy_id=policy.id)
        await groups_service.remove_member(scoped, group_id=group.id, user_id=user.id, actor_id=admin.id)
        await mfa_service.reset_mfa(scoped, await scoped.get(User, user.id), admin.id)
        await groups_service.delete_group(scoped, await scoped.get(Group, group.id), actor_id=admin.id)
        await record_sample(scoped, await _any_node(scoped))  # also prunes old samples
        await scoped.flush()
        await scoped.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM security_events WHERE id IS NULL",
        "UPDATE security_events SET metadata_json = metadata_json WHERE id IS NULL",
    ],
)
async def test_admin_role_cannot_rewrite_the_audit_trail(roles, statement):
    async with roles["admin"]() as scoped:
        with pytest.raises(DBAPIError, match="permission denied"):
            await scoped.execute(text(statement))
