from uuid import uuid4

import pytest

from tests.conftest import login_with_mfa_enrollment, make_user


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
