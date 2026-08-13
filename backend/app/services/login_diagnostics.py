"""Roadmap Phase B / B1.10.6 — Login Diagnostics: "why can't this user log
in?" for support/admin use. Strictly read-only: never tests a password,
never authenticates on the user's behalf, never returns a secret. Every
signal here is something /auth/login itself already checks — this module
doesn't invent new login rules, it just makes the existing ones visible.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sessions import get_login_lockout_status
from app.models.enums import MFA_MANDATORY_ROLES
from app.models.role import Role
from app.models.security_event import SecurityEvent
from app.models.user import User
from app.services.ldap_config_service import get_effective_ldap_config

_RECENT_FAILURE_WINDOW = timedelta(hours=1)
_RECENT_FAILURE_LIMIT = 10


async def diagnose_login(db: AsyncSession, username: str) -> dict:
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    ldap_config = await get_effective_ldap_config(db)
    ldap_enabled = ldap_config is not None

    since = datetime.now(UTC) - _RECENT_FAILURE_WINDOW
    events_result = await db.execute(
        select(SecurityEvent)
        .where(
            SecurityEvent.event_type.in_(["USER_LOGIN_FAILED", "LOGIN_LOCKED"]),
            SecurityEvent.metadata_json["username"].astext == username,
            SecurityEvent.created_at >= since,
        )
        .order_by(SecurityEvent.created_at.desc())
        .limit(_RECENT_FAILURE_LIMIT)
    )
    recent_events = [
        {"event_type": e.event_type.value, "created_at": e.created_at} for e in events_result.scalars()
    ]

    lockout = await get_login_lockout_status(username)

    reasons: list[str] = []
    if lockout["locked"]:
        remaining = lockout["locked_seconds_remaining"] or 0
        minutes = (remaining + 59) // 60
        reasons.append(f"Account is locked out from repeated failed attempts (clears in ~{minutes} min).")

    if user is None:
        if ldap_enabled:
            reasons.append(
                "No local account found for this username. If they're expected to log in via LDAP, "
                "their first successful LDAP login provisions the account automatically — check the "
                "username matches their LDAP identity exactly (provisioning is exact-match only)."
            )
        else:
            reasons.append("No account found for this username — check for a typo, or whether it was ever created.")
    else:
        if not user.is_active:
            reasons.append("Account is disabled by an administrator.")
        role_result = await db.get(Role, user.role_id)
        role_name = role_result.name if role_result else None
        if role_name in MFA_MANDATORY_ROLES and not user.mfa_enabled:
            reasons.append(
                f"Role {role_name} requires MFA, and none is enrolled yet — this doesn't block login by "
                "itself, but the user will be forced through enrollment on their next successful "
                "password check rather than reaching the dashboard directly."
            )
        if user.password_hash is None and not ldap_enabled:
            reasons.append(
                "This account has no local password set (LDAP-provisioned) and LDAP is not currently enabled "
                "— there is no way for this account to authenticate right now."
            )

    if not reasons and len(recent_events) == 0:
        reasons.append("No obvious blocker found. If they still can't log in, the password itself may be wrong — this cannot be verified without asking the user to try again.")

    return {
        "username": username,
        "user_id": user.id if user is not None else None,
        "account_exists": user is not None,
        "is_active": user.is_active if user is not None else None,
        "mfa_enabled": user.mfa_enabled if user is not None else None,
        "auth_source": ("local" if user.password_hash is not None else "ldap") if user is not None else None,
        "ldap_enabled": ldap_enabled,
        "lockout": lockout,
        "recent_failed_attempts": recent_events,
        "possible_reasons": reasons,
    }
