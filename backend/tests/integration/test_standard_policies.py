"""Standard policy templates are created once per installation: a new
template arrives with an update, but one an admin renamed or archived is
never re-created (app/services/standard_policies.py).

Uses its own pytest_-named template list instead of the real one, so the
real templates in the shared dev database are left alone.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.policy import GroupPolicy, Policy, PolicyVersion
from app.models.system_state import SYSTEM_STATE_ID, SystemState
from app.services import standard_policies
from app.services.policies import rename_policy
from tests.conftest import PREFIX


def _template(name: str) -> dict:
    return {
        "name": name,
        "policy_type": "SESSION",
        "description": "test template",
        "content": {"screen_width": 1280, "screen_height": 720},
        "file_rules": [],
    }


@pytest_asyncio.fixture(autouse=True)
async def _forget_test_templates(db):
    """The seeded-template bookkeeping is a single installation-wide row;
    drop the pytest_ names this module adds to it.
    """
    state = await db.get(SystemState, SYSTEM_STATE_ID)
    created_row = state is None
    if created_row:
        # test_setup.py deletes the row to simulate a fresh install.
        db.add(SystemState(id=SYSTEM_STATE_ID, initialized=True))
        await db.commit()
    yield
    state = await db.get(SystemState, SYSTEM_STATE_ID)
    await db.refresh(state)
    if created_row:
        await db.delete(state)
    else:
        state.seeded_policy_templates = [n for n in state.seeded_policy_templates if not n.startswith(PREFIX)]
    await db.commit()


async def _policy_named(db, name: str) -> Policy | None:
    return (await db.execute(select(Policy).where(Policy.name == name))).scalar_one_or_none()


@pytest.mark.asyncio
async def test_templates_are_created_published_unattached_and_only_once(db, monkeypatch):
    first = f"{PREFIX}template-a-{uuid.uuid4().hex}"
    monkeypatch.setattr(standard_policies, "STANDARD_POLICIES", [_template(first)])

    created, skipped = await standard_policies.seed_standard_policies(db)
    await db.commit()
    assert created == [first] and skipped == []
    policy = await _policy_named(db, first)
    assert policy is not None and policy.current_version_id is not None
    version = await db.get(PolicyVersion, policy.current_version_id)
    assert version.created_by is None, "templates are system-authored, not tied to an admin account"
    attached = await db.execute(select(GroupPolicy.id).where(GroupPolicy.policy_id == policy.id))
    assert attached.first() is None, "a template must never be attached to a group by seeding"

    # An admin renames it; the next update must not bring the original back.
    await rename_policy(db, policy, name=f"{first}-renamed")
    await db.commit()
    created, skipped = await standard_policies.seed_standard_policies(db)
    await db.commit()
    assert created == [] and skipped == []
    assert await _policy_named(db, first) is None

    # A template added by a newer release is created on the next run.
    second = f"{PREFIX}template-b-{uuid.uuid4().hex}"
    monkeypatch.setattr(standard_policies, "STANDARD_POLICIES", [_template(first), _template(second)])
    created, _ = await standard_policies.seed_standard_policies(db)
    await db.commit()
    assert created == [second]


@pytest.mark.asyncio
async def test_existing_policy_with_a_template_name_is_kept_and_recorded(db, monkeypatch):
    """Installations seeded by the old standalone script already have the
    templates; they must be recorded, not duplicated or overwritten.
    """
    name = f"{PREFIX}template-existing-{uuid.uuid4().hex}"
    db.add(Policy(name=name, policy_type="SESSION", description="made by an admin"))
    await db.commit()
    monkeypatch.setattr(standard_policies, "STANDARD_POLICIES", [_template(name)])

    created, skipped = await standard_policies.seed_standard_policies(db)
    await db.commit()

    assert created == [] and skipped == [name]
    assert (await _policy_named(db, name)).description == "made by an admin"
    state = await db.get(SystemState, SYSTEM_STATE_ID)
    await db.refresh(state)
    assert name in state.seeded_policy_templates
