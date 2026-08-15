"""Roadmap B1.8.2 — admin-portal LDAP configuration API (docs/adr/
0016-ldap-admin-configuration.md).

Reuses, never duplicates: LdapAuthProvider/LdapConnectionConfig for both
the real login path (app/api/auth.py) and this module's connection test
(app/core/auth_providers/ldap.py), require_role for RBAC (app/core/deps.py),
record_security_event for audit (app/services/security_events.py), and
app/core/crypto.py's Fernet helpers for the bind password at rest.

Edit -> Test -> Save -> Activate (Section 6): POST /admin/ldap/test is
fully stateless (never touches the DB, never reads the stored config) so a
broken candidate config can be tried freely. PUT /admin/ldap/config, when
the request would leave LDAP enabled, re-runs the exact same
test_connection() against the *candidate* config first and rejects with
422 before writing anything if it fails — the existing row (if any) is
never touched by a rejected update. This is deliberately not a separate
draft/pending-config table — a stricter validation gate on the single
write path already satisfies "a failed test/save can't destroy the active
config" without a second state machine.
"""


from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.admin_ldap import (
    LdapConfigResponse,
    LdapConfigUpdateRequest,
    LdapTestRequest,
    LdapTestResponse,
    LdapTestStepResponse,
)
from app.core.auth_providers.ldap import LdapAuthProvider, LdapConnectionConfig, LdapTestResult
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.enums import SecurityEventType
from app.models.ldap_config import LDAP_CONFIG_ID, LdapConfig
from app.models.user import User
from app.services.ldap_config_service import get_ldap_config_row
from app.services.security_events import record_security_event

router = APIRouter(prefix="/admin/ldap", tags=["admin"], dependencies=[Depends(require_role("ADMIN"))])


def _test_result_response(result: LdapTestResult) -> LdapTestResponse:
    return LdapTestResponse(
        success=result.success,
        steps=[LdapTestStepResponse(name=s.name, ok=s.ok, detail=s.detail) for s in result.steps],
        groups_discovered=result.groups_discovered,
    )


@router.get("/config", response_model=LdapConfigResponse)
async def get_config(db: AsyncSession = Depends(get_db)) -> LdapConfigResponse:
    row = await get_ldap_config_row(db)
    if row is None:
        return LdapConfigResponse.empty()
    return LdapConfigResponse.from_model(row)


@router.post("/test", response_model=LdapTestResponse)
async def test_config(
    payload: LdapTestRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LdapTestResponse:
    """Stateless: never reads or writes the persisted config. Exists so an
    admin can try out a candidate configuration — including one that would
    replace an already-saved, working setup — without any risk of it being
    silently persisted just by testing it.
    """
    config = LdapConnectionConfig(
        server_uri=payload.server_uri,
        use_starttls=payload.use_starttls,
        bind_dn=payload.bind_dn,
        bind_password=payload.bind_password,
        base_dn=payload.base_dn,
        user_search_filter=payload.user_search_filter,
        group_attribute=payload.group_attribute,
    )
    result = await LdapAuthProvider(config).test_connection(test_username=payload.test_username)
    await record_security_event(
        db,
        SecurityEventType.LDAP_CONNECTION_TESTED,
        user_id=current_user.id,
        metadata={"server_uri": payload.server_uri, "success": result.success},
    )
    await db.commit()
    return _test_result_response(result)


@router.put("/config", response_model=LdapConfigResponse)
async def update_config(
    payload: LdapConfigUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LdapConfigResponse:
    row = await get_ldap_config_row(db)
    was_enabled = row.enabled if row is not None else False

    # Section 4: an empty/omitted password on update must never clear an
    # already-stored secret. Only a non-empty, explicitly submitted value
    # ever replaces it.
    if payload.bind_password:
        bind_password_encrypted = encrypt_secret(payload.bind_password)
        effective_bind_password = payload.bind_password
    elif row is not None:
        bind_password_encrypted = row.bind_password_encrypted
        effective_bind_password = decrypt_secret(row.bind_password_encrypted) if row.bind_password_encrypted else ""
    else:
        bind_password_encrypted = None
        effective_bind_password = ""

    if payload.enabled:
        # Section 6: a config change that would (re)activate LDAP is
        # re-verified against the exact real auth path before anything is
        # written — a broken new config never overwrites a working one.
        candidate = LdapConnectionConfig(
            server_uri=payload.server_uri,
            use_starttls=payload.use_starttls,
            bind_dn=payload.bind_dn,
            bind_password=effective_bind_password,
            base_dn=payload.base_dn,
            user_search_filter=payload.user_search_filter,
            group_attribute=payload.group_attribute,
        )
        test_result = await LdapAuthProvider(candidate).test_connection()
        if not test_result.success:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": "LDAP connection test failed; existing configuration was not changed",
                    "steps": [
                        {"name": s.name, "ok": s.ok, "detail": s.detail} for s in test_result.steps
                    ],
                },
            )

    if row is None:
        row = LdapConfig(id=LDAP_CONFIG_ID)
        db.add(row)

    row.enabled = payload.enabled
    row.server_uri = payload.server_uri
    row.use_starttls = payload.use_starttls
    row.bind_dn = payload.bind_dn
    row.bind_password_encrypted = bind_password_encrypted
    row.base_dn = payload.base_dn
    row.user_search_filter = payload.user_search_filter
    row.group_attribute = payload.group_attribute
    row.group_role_mapping = payload.group_role_mapping
    row.updated_by = current_user.id

    await record_security_event(
        db,
        SecurityEventType.LDAP_CONFIG_CHANGED,
        user_id=current_user.id,
        metadata={
            "server_uri": payload.server_uri,
            "use_starttls": payload.use_starttls,
            "base_dn": payload.base_dn,
            "bind_password_changed": bool(payload.bind_password),
        },
    )
    if payload.enabled and not was_enabled:
        await record_security_event(db, SecurityEventType.LDAP_ENABLED, user_id=current_user.id)
    elif not payload.enabled and was_enabled:
        await record_security_event(db, SecurityEventType.LDAP_DISABLED, user_id=current_user.id)

    await db.commit()
    await db.refresh(row)
    return LdapConfigResponse.from_model(row)
