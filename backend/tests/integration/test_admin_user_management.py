import pytest

from tests.conftest import login_with_mfa_enrollment, make_user


@pytest.mark.asyncio
async def test_user_list_is_admin_only_and_paginated(db, client):
    normal, normal_password = await make_user(db, role_name="USER")
    response = await client.post(
        "/auth/login", json={"username": normal.username, "password": normal_password}
    )
    forbidden = await client.get(
        "/admin/users", cookies={"openrbi_session": response.cookies.get("openrbi_session")}
    )
    assert forbidden.status_code == 403

    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)
    result = await client.get("/admin/users?limit=1&offset=0", cookies={"openrbi_session": cookie})
    assert result.status_code == 200, result.text
    body = result.json()
    assert len(body["items"]) == 1
    assert body["total"] >= 2
    assert body["stats"]["total"] >= body["total"]
    assert "ADMIN" in body["roles"]


@pytest.mark.asyncio
async def test_user_search_role_status_and_source_filters(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    local, _ = await make_user(db, role_name="USER")
    ldap, _ = await make_user(db, role_name="USER")
    ldap.password_hash = None
    ldap.is_active = False
    db.add(ldap)
    await db.commit()
    cookie = await login_with_mfa_enrollment(client, admin.username, password)

    result = await client.get(
        f"/admin/users?search={ldap.username}&role=USER&status=DISABLED&auth_source=LDAP",
        cookies={"openrbi_session": cookie},
    )
    assert result.status_code == 200, result.text
    assert [item["id"] for item in result.json()["items"]] == [str(ldap.id)]
    assert result.json()["items"][0]["auth_source"] == "LDAP"
    assert local.id != ldap.id


@pytest.mark.asyncio
async def test_ldap_password_reset_and_admin_self_disable_are_rejected(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    ldap, _ = await make_user(db, role_name="USER")
    ldap.password_hash = None
    db.add(ldap)
    await db.commit()
    cookie = await login_with_mfa_enrollment(client, admin.username, password)

    reset = await client.post(
        f"/admin/users/{ldap.id}/reset-password",
        json={"new_password": "A-strong-new-password-123!"},
        cookies={"openrbi_session": cookie},
    )
    assert reset.status_code == 400
    assert "LDAP" in reset.json()["detail"]

    disable = await client.post(
        f"/admin/users/{admin.id}/disable", cookies={"openrbi_session": cookie}
    )
    assert disable.status_code == 400
