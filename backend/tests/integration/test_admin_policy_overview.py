import uuid

import pytest

from app.services.policies import create_draft_version, create_policy, publish_version
from tests.conftest import PREFIX, login_with_mfa_enrollment, make_user


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


@pytest.mark.asyncio
async def test_update_policy_renames_and_updates_description(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)
    unique_key = f"{PREFIX}{uuid.uuid4().hex[:12]}"
    policy = await create_policy(db, name=f"{unique_key}-original", policy_type="MIME", actor_id=admin.id)
    await db.commit()

    response = await client.put(
        f"/admin/policies/{policy.id}",
        json={"name": f"{unique_key}-renamed", "description": "New description"},
        cookies={"openrbi_session": cookie},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == f"{unique_key}-renamed"
    assert body["description"] == "New description"


@pytest.mark.asyncio
async def test_update_policy_rejects_duplicate_name(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)
    unique_key = f"{PREFIX}{uuid.uuid4().hex[:12]}"
    taken = await create_policy(db, name=f"{unique_key}-taken", policy_type="MIME", actor_id=admin.id)
    other = await create_policy(db, name=f"{unique_key}-other", policy_type="MIME", actor_id=admin.id)
    await db.commit()

    response = await client.put(
        f"/admin/policies/{other.id}",
        json={"name": taken.name},
        cookies={"openrbi_session": cookie},
    )

    assert response.status_code == 400, response.text


@pytest.mark.asyncio
async def test_update_policy_rejects_empty_name(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)
    unique_key = f"{PREFIX}{uuid.uuid4().hex[:12]}"
    policy = await create_policy(db, name=f"{unique_key}-original", policy_type="MIME", actor_id=admin.id)
    await db.commit()

    response = await client.put(
        f"/admin/policies/{policy.id}",
        json={"name": "   "},
        cookies={"openrbi_session": cookie},
    )

    assert response.status_code == 400, response.text


@pytest.mark.asyncio
async def test_update_policy_returns_404_for_unknown_policy(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)

    response = await client.put(
        f"/admin/policies/{uuid.uuid4()}",
        json={"name": "Doesn't matter"},
        cookies={"openrbi_session": cookie},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_policy_is_admin_only(db, client):
    user, password = await make_user(db, role_name="USER")
    admin, _ = await make_user(db, role_name="ADMIN")
    unique_key = f"{PREFIX}{uuid.uuid4().hex[:12]}"
    policy = await create_policy(db, name=f"{unique_key}-original", policy_type="MIME", actor_id=admin.id)
    await db.commit()
    login = await client.post("/auth/login", json={"username": user.username, "password": password})

    response = await client.put(
        f"/admin/policies/{policy.id}",
        json={"name": f"{unique_key}-attempted"},
        cookies={"openrbi_session": login.cookies.get("openrbi_session")},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_there_is_no_hard_delete_for_policies(db, client):
    """Findings addendum 3, #13 — deliberate, not a gap: past sessions and
    quarantine decisions reference their exact PolicyVersion for audit.
    """
    admin, password = await make_user(db, role_name="ADMIN")
    policy = await create_policy(db, name=f"{PREFIX}nodelete-{uuid.uuid4().hex}", policy_type="MIME", actor_id=admin.id)
    await db.commit()
    cookie = await login_with_mfa_enrollment(client, admin.username, password)

    response = await client.delete(f"/admin/policies/{policy.id}", cookies={"openrbi_session": cookie})

    assert response.status_code == 405


@pytest.mark.asyncio
async def test_archive_hides_policy_from_default_list_and_restore_brings_it_back(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    unique_key = uuid.uuid4().hex
    policy = await create_policy(db, name=f"{PREFIX}archive-{unique_key}", policy_type="MIME", actor_id=admin.id)
    await db.commit()
    cookie = await login_with_mfa_enrollment(client, admin.username, password)
    cookies = {"openrbi_session": cookie}

    archived = await client.post(f"/admin/policies/{policy.id}/archive", cookies=cookies)
    assert archived.status_code == 200, archived.text
    assert archived.json()["archived_at"] is not None

    default_view = (await client.get(f"/admin/policies?search={unique_key}", cookies=cookies)).json()
    assert default_view["total"] == 0
    assert default_view["stats"]["archived"] >= 1
    archived_view = (await client.get(f"/admin/policies?search={unique_key}&archived=true", cookies=cookies)).json()
    assert [item["id"] for item in archived_view["items"]] == [str(policy.id)]

    again = await client.post(f"/admin/policies/{policy.id}/archive", cookies=cookies)
    assert again.status_code == 409

    restored = await client.post(f"/admin/policies/{policy.id}/restore", cookies=cookies)
    assert restored.status_code == 200, restored.text
    assert restored.json()["archived_at"] is None
    assert (await client.get(f"/admin/policies?search={unique_key}", cookies=cookies)).json()["total"] == 1


@pytest.mark.asyncio
async def test_archive_is_refused_while_attached_and_archived_policy_cannot_be_attached(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    unique_key = uuid.uuid4().hex
    policy = await create_policy(db, name=f"{PREFIX}attached-{unique_key}", policy_type="MIME", actor_id=admin.id)
    await db.commit()
    cookie = await login_with_mfa_enrollment(client, admin.username, password)
    cookies = {"openrbi_session": cookie}
    group = await client.post("/admin/groups", json={"name": f"{PREFIX}group-{unique_key}"}, cookies=cookies)
    assert group.status_code in (200, 201), group.text
    group_id = group.json()["id"]

    assert (await client.post(f"/admin/policies/{policy.id}/groups/{group_id}", cookies=cookies)).status_code == 204
    refused = await client.post(f"/admin/policies/{policy.id}/archive", cookies=cookies)
    assert refused.status_code == 409
    assert "attached" in refused.json()["detail"]

    assert (await client.delete(f"/admin/policies/{policy.id}/groups/{group_id}", cookies=cookies)).status_code == 204
    assert (await client.post(f"/admin/policies/{policy.id}/archive", cookies=cookies)).status_code == 200
    reattach = await client.post(f"/admin/policies/{policy.id}/groups/{group_id}", cookies=cookies)
    assert reattach.status_code == 409
