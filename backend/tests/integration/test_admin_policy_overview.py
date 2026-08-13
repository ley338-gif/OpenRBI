import uuid

import pytest

from app.services.policies import create_draft_version, create_policy, publish_version
from tests.conftest import login_with_mfa_enrollment, make_user


@pytest.mark.asyncio
async def test_policy_overview_is_admin_only(db, client):
    user, password = await make_user(db, role_name="USER")
    login = await client.post("/auth/login", json={"username": user.username, "password": password})

    response = await client.get(
        "/admin/policies", cookies={"openrbi_session": login.cookies.get("openrbi_session")}
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_policy_overview_filters_sorts_and_paginates(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    unique_key = uuid.uuid4().hex
    policy = await create_policy(
        db,
        name=f"Policy {unique_key}",
        description=f"Description {unique_key}",
        policy_type="MIME",
        actor_id=admin.id,
    )
    draft = await create_draft_version(
        db,
        policy,
        content={},
        file_rules=[{"rule_type": "MIME", "match_pattern": "application/pdf", "action": "DENY", "priority": 10}],
        actor_id=admin.id,
    )
    await publish_version(db, policy, draft, actor_id=admin.id)
    await db.commit()
    cookie = await login_with_mfa_enrollment(client, admin.username, password)

    response = await client.get(
        f"/admin/policies?search={unique_key}&policy_type=MIME&status_filter=PUBLISHED&usage=UNASSIGNED&sort_by=updated_at&sort_dir=desc&offset=0&limit=1",
        cookies={"openrbi_session": cookie},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(policy.id)
    assert body["items"][0]["current_version_number"] == 1
    assert body["items"][0]["has_draft"] is False
    assert body["items"][0]["version_count"] == 1
    assert body["items"][0]["updated_by"] == admin.username
    assert body["stats"]["total"] >= 1
    assert body["stats"]["published"] >= 1


@pytest.mark.asyncio
async def test_create_policy_accepts_description_and_returns_draft_state(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)
    unique_key = uuid.uuid4().hex

    response = await client.post(
        "/admin/policies",
        json={"name": f"Created {unique_key}", "description": f"Purpose {unique_key}", "policy_type": "SOURCE"},
        cookies={"openrbi_session": cookie},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["description"] == f"Purpose {unique_key}"
    assert body["current_version_id"] is None
    assert body["version_count"] == 0
