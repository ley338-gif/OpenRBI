"""Roadmap Phase B / B1.3 — resolves an LDAP login's group DNs to an
OpenRBI role, and reconciles/just-in-time-provisions the local User row a
successful LDAP bind authenticates as. See docs/adr/0015 for the
identity-resolution and role-authority decisions this implements.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.enums import SecurityEventType
from app.models.role import Role
from app.models.user import User
from app.services.security_events import record_security_event

_ROLE_PRECEDENCE = ("ADMIN", "SECURITY_REVIEWER", "USER")


def resolve_role_from_ldap_groups(group_dns: list[str]) -> str:
    """DN comparison is exact-string, case-sensitive — matching the DN
    exactly as configured in OPENRBI_LDAP_GROUP_ROLE_MAPPING. A real DN
    case-insensitivity implementation would need to parse and normalize
    each RDN component per its attribute type's matching rule; not done
    here, documented as a known limitation (docs/admin-guide.md) rather
    than silently assumed correct.

    No matching group -> USER, the least-privileged role, never an
    implicit elevated default.
    """
    settings = get_settings()
    mapped_roles = {settings.ldap_group_role_mapping[dn] for dn in group_dns if dn in settings.ldap_group_role_mapping}
    for role_name in _ROLE_PRECEDENCE:
        if role_name in mapped_roles:
            return role_name
    return "USER"


async def resolve_or_provision_ldap_user(db: AsyncSession, username: str, ldap_group_dns: list[str]) -> User:
    """Called only after LdapAuthProvider has already verified the
    password via a real bind — this function never re-checks credentials,
    only resolves *which* local User row this successful login belongs to
    and what role it should have.

    Exact-username-match reconciliation (docs/adr/0015): if a local
    account with this exact username already exists, that row is reused
    rather than creating a second one. Role authority depends on whether
    that existing account has a local password:
      - password_hash is NULL (itself LDAP-provisioned): role is
        re-derived from the *current* LDAP groups on every login, same
        "recompute from source of truth" principle already applied to
        MFA-mandatory-role enforcement.
      - password_hash is set (an admin-managed local account that happens
        to share a username with an LDAP identity): role stays exactly as
        the admin configured it. A deliberately-provisioned local account
        (e.g. an emergency ADMIN access path) must never be silently
        downgraded by an incidental LDAP group mismatch — confirmed
        explicitly as the intended behavior, not inferred.
    """
    resolved_role_name = resolve_role_from_ldap_groups(ldap_group_dns)

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user is not None:
        if user.password_hash is None and user.is_active:
            role = await db.get(Role, user.role_id)
            if role.name != resolved_role_name:
                new_role = await _get_role_by_name(db, resolved_role_name)
                user.role_id = new_role.id
                await record_security_event(
                    db,
                    SecurityEventType.USER_ROLE_CHANGED,
                    user_id=user.id,
                    metadata={"reason": "ldap_group_mapping", "new_role": resolved_role_name},
                )
        return user

    role = await _get_role_by_name(db, resolved_role_name)
    new_user = User(
        id=uuid.uuid4(),
        username=username,
        password_hash=None,
        role_id=role.id,
        is_active=True,
        mfa_enabled=False,
    )
    db.add(new_user)
    await db.flush()
    await record_security_event(
        db,
        SecurityEventType.USER_PROVISIONED_VIA_LDAP,
        user_id=new_user.id,
        metadata={"username": username, "role": resolved_role_name},
    )
    return new_user


async def _get_role_by_name(db: AsyncSession, role_name: str) -> Role:
    result = await db.execute(select(Role).where(Role.name == role_name))
    role = result.scalar_one_or_none()
    if role is None:
        raise RuntimeError(f"role '{role_name}' is not seeded — this should never happen for a fixed MVP role")
    return role
