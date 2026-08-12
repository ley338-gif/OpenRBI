from fastapi import Depends, FastAPI

from app.auth import require_control_plane_token

app = FastAPI(
    title="OpenRBI Session Agent",
    version="0.1.0",
    description=(
        "Internal-only privileged service for browser sandbox lifecycle. "
        "Not exposed publicly; see docs/adr/0004 and 0005."
    ),
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/nodes/self", dependencies=[Depends(require_control_plane_token)])
async def node_status() -> dict[str, str]:
    """Placeholder for BrowserNode status/capacity reporting (Phase 6/23)."""
    return {"status": "not_implemented"}
