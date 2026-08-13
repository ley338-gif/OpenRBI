import pytest

from tests.conftest import login_with_mfa_enrollment, make_user


@pytest.mark.asyncio
async def test_group_overview_is_admin_only(db, client):
    user, password = await make_user(db, username="groups-user", role_name="USER")
    login = await client.post("/auth/login", json={"username": user.username, "password": password})
    response = await client.get(
        "/admin/groups-overview",
        cookies={"openrbi_session": login.cookies.get("openrbi_session")},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_group_overview_search_pagination_and_stats(db, client):
    admin, password = await make_user(db, username="groups-admin", role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)
    created = await client.post(
        "/admin/groups",
        json={"name": "Radiology Operations", "description": "Clinical browser access"},
        cookies={"openrbi_session": cookie},
    )
    assert created.status_code == 201, created.text

    response = await client.get(
        "/admin/groups-overview?search=clinical&limit=1&offset=0",
        cookies={"openrbi_session": cookie},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Radiology Operations"
    assert body["items"][0]["policies"] == []
    assert body["stats"]["total"] >= 1
    assert body["stats"]["memberships"] >= 0
    assert body["stats"]["with_policies"] >= 0


@pytest.mark.asyncio
async def test_group_delete_removes_group_but_not_user(db, client):
    admin, password = await make_user(db, username="groups-delete-admin", role_name="ADMIN")
    member, _ = await make_user(db, username="groups-surviving-user", role_name="USER")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)
    created = await client.post(
        "/admin/groups",
        json={"name": "Temporary Group", "description": None},
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
