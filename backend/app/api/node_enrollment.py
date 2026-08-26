"""Roadmap B2.1 (docs/adr/0023-node-enrollment-and-trust-model.md) — a new
Session Agent's own registration call. Deliberately unauthenticated (no
admin session exists on a node's own call path) but closed by the
single-use enrollment token itself plus the same per-key rate limiting
app/api/setup.py's bootstrap endpoint already uses — mirrors that file's
"unauthenticated but not open" pattern exactly.

Separate router from app/api/admin_nodes.py on purpose: that router's
`require_role` dependency is applied at the router level, and this one
endpoint must never be gated by it.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.nodes import BrowserNodeResponse, NodeEnrollRequest
from app.core.node_enrollment_tokens import consume_token
from app.core.sessions import clear_login_failures, is_login_locked, record_login_failure
from app.db.session import get_db
from app.services.nodes import NodeServiceError, enroll_node

router = APIRouter(prefix="/admin/nodes", tags=["admin"])

_RATE_LIMIT_KEY = "__node_enrollment__"


@router.post("/enroll", response_model=BrowserNodeResponse)
async def enroll_node_endpoint(
    payload: NodeEnrollRequest, db: AsyncSession = Depends(get_db)
) -> BrowserNodeResponse:
    if await is_login_locked(_RATE_LIMIT_KEY):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="too many failed enrollment attempts")

    if not await consume_token(payload.enrollment_token):
        await record_login_failure(_RATE_LIMIT_KEY)
        # Same generic-enough message for "wrong/expired token" and any
        # other rejection — no internal detail, matching setup.py's
        # create_admin error handling.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid or expired enrollment token")
    await clear_login_failures(_RATE_LIMIT_KEY)

    try:
        node = await enroll_node(db, hostname=payload.hostname, api_token=payload.api_token)
    except NodeServiceError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(node)
    return BrowserNodeResponse.from_model(node)
