from app.build_info import BUILD_INFO
from app.main import app


async def test_health_exposes_non_secret_build_metadata(client):
    response = await client.get("/health")
    response.raise_for_status()
    body = response.json()

    assert body == {"status": "ok", **BUILD_INFO.as_dict()}
    assert body["version"]
    assert app.version == body["version"]
    assert set(body) == {"status", "version", "commit_sha", "build_date"}
