"""GET /admin/security-events rejects page parameters outside their range
with 422 instead of passing them to the database (a negative LIMIT was a 500).
"""

import pytest

from tests.conftest import login_with_mfa_enrollment, make_user


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["limit=0", "limit=-1", "limit=501", "offset=-1"])
async def test_out_of_range_paging_is_rejected(db, client, query):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)

    response = await client.get(f"/admin/security-events?{query}", cookies={"openrbi_session": cookie})

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_in_range_paging_is_accepted(db, client):
    admin, password = await make_user(db, role_name="ADMIN")
    cookie = await login_with_mfa_enrollment(client, admin.username, password)

    response = await client.get("/admin/security-events?limit=1&offset=0", cookies={"openrbi_session": cookie})

    assert response.status_code == 200, response.text
    assert len(response.json()) <= 1
