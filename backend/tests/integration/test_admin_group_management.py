from uuid import uuid4

import pytest

from tests.conftest import PREFIX, login_with_mfa_enrollment, make_user


@pytest.mark.asyncio
async def test_group_overview_is_admin_only(db, client):
    user, password = await make_user(db, role_name="USER")
    login = await client.post("/auth/login", json={"username": user.username, "password": password})
    response = await client.get(
        "/admin/groups-overview",
        cookies={"openrbi_session": login.cookies.get("openrbi_session")},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_group_overview_search_pagination_and_stats(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)
    unique_key = uuid4().hex
    group_name = f"Radiology Operations {unique_key}"
    created = await client.post(
        "/admin/groups",
        json={"name": group_name, "description": f"Clinical browser access {unique_key}"},
        cookies={"openrbi_session": cookie},
    )
    assert created.status_code == 201, created.text

    response = await client.get(
        f"/admin/groups-overview?search={unique_key}&limit=1&offset=0",
        cookies={"openrbi_session": cookie},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == group_name
    assert body["items"][0]["policies"] == []
    assert body["stats"]["total"] >= 1
    assert body["stats"]["memberships"] >= 0
    assert body["stats"]["with_policies"] >= 0


@pytest.mark.asyncio
async def test_group_delete_removes_group_but_not_user(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    member, _ = await make_user(db, role_name="USER")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)
    created = await client.post(
        "/admin/groups",
        json={"name": f"Temporary Group {uuid4().hex}", "description": None},
        cookies={"openrbi_session": cookie},
    )
    group_id = created.json()["id"]
    update = await client.put(
        f"/admin/users/{member.id}/groups",
        json={"group_ids": [group_id]},
        cookies={"openrbi_session": cookie},
    )
    assert update.status_code == 200, update.text
    deleted = await client.delete(
        f"/admin/groups/{group_id}", cookies={"openrbi_session": cookie}
    )
    assert deleted.status_code == 204
    still_exists = await client.get(
        f"/admin/users/{member.id}", cookies={"openrbi_session": cookie}
    )
    assert still_exists.status_code == 200


@pytest.mark.asyncio
async def test_group_detail_returns_404_for_unknown_group(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)
    response = await client.get(f"/admin/groups/{uuid4()}", cookies={"openrbi_session": cookie})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_group_detail_shows_real_members_and_policies(db, client):
    """The Group Detail page (previously nonexistent — there was no
    /admin/groups/{id} endpoint at all, and no UI anywhere to attach a
    policy to a group or see its members) must reflect real data: an
    actual member count from a real membership, and actual attached
    policies with usable ids (not just names), since the UI needs the id
    to offer a "detach" action.
    """
    admin, password = await make_user(db, role_name="ADMIN")
    member, _ = await make_user(db, role_name="USER")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)

    group_resp = await client.post(
        "/admin/groups",
        json={"name": f"{PREFIX}group_{uuid4().hex[:8]}", "description": "test group"},
        cookies={"openrbi_session": cookie},
    )
    assert group_resp.status_code == 201, group_resp.text
    group_id = group_resp.json()["id"]

    membership = await client.put(
        f"/admin/users/{member.id}/groups",
        json={"group_ids": [group_id]},
        cookies={"openrbi_session": cookie},
    )
    assert membership.status_code == 200, membership.text

    policy_resp = await client.post(
        "/admin/policies",
        json={"name": f"{PREFIX}policy_{uuid4().hex[:8]}", "policy_type": "SESSION", "description": None},
        cookies={"openrbi_session": cookie},
    )
    assert policy_resp.status_code == 201, policy_resp.text
    policy_id = policy_resp.json()["id"]
    policy_name = policy_resp.json()["name"]

    attach = await client.post(
        f"/admin/policies/{policy_id}/groups/{group_id}", cookies={"openrbi_session": cookie}
    )
    assert attach.status_code == 204, attach.text

    detail = await client.get(f"/admin/groups/{group_id}", cookies={"openrbi_session": cookie})
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["member_count"] == 1
    assert body["policies"] == [{"id": policy_id, "name": policy_name, "policy_type": "SESSION"}]

    # The reverse direction (PolicyDetail's own group picker) must see the
    # same link, with an id — not just a display name — so it can offer
    # its own "detach" action.
    policy_detail = await client.get(f"/admin/policies/{policy_id}", cookies={"openrbi_session": cookie})
    assert policy_detail.status_code == 200
    assert policy_detail.json()["assigned_groups"] == [{"id": group_id, "name": group_resp.json()["name"]}]

    detach = await client.delete(
        f"/admin/policies/{policy_id}/groups/{group_id}", cookies={"openrbi_session": cookie}
    )
    assert detach.status_code == 204, detach.text
    detail_after = await client.get(f"/admin/groups/{group_id}", cookies={"openrbi_session": cookie})
    assert detail_after.json()["policies"] == []


@pytest.mark.asyncio
async def test_group_management_endpoints_are_admin_only(db, client):
    user, password = await make_user(db, role_name="USER")
    login = await client.post("/auth/login", json={"username": user.username, "password": password})
    cookie = login.cookies.get("openrbi_session")
    assert (await client.get(f"/admin/groups/{uuid4()}", cookies={"openrbi_session": cookie})).status_code == 403
