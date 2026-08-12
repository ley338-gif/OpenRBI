"""First, required AuthProvider implementation — wraps exactly what
app/api/auth.py's login() already did inline before this refactor
(Roadmap B1.1): look up the user by username, verify their Argon2 hash.

Pure move, not a rewrite: the disabled-account check, the password
verification call, and the "don't distinguish unknown-user from wrong-
password" behavior are unchanged from the pre-refactor version — see
backend/tests/integration/test_auth_and_mfa.py's existing local-login tests,
which this refactor must keep passing byte-for-byte.

Roadmap B1.3 adds one real behavior change on top of that unchanged core:
users.password_hash can now be NULL (a JIT-provisioned LDAP-only account,
docs/adr/0015) — explicitly rejected here rather than passed into
verify_password(), which was never designed to receive one.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_providers.base import AuthResult
from app.core.security import verify_password
from app.models.user import User


class LocalAuthProvider:
    async def authenticate(self, db: AsyncSession, username: str, password: str) -> AuthResult:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()

        if (
            user is None
            or not user.is_active
            or user.password_hash is None
            or not verify_password(password, user.password_hash)
        ):
            return AuthResult(success=False, matched_user_id=user.id if user is not None else None)

        return AuthResult(success=True, username=user.username, matched_user_id=user.id)

    async def health(self) -> bool:
        # No external dependency of its own — local auth is only ever as
        # available as the database, which already has its own health
        # check (GET /admin/health). Always True here, not a stub for a
        # check that doesn't exist yet.
        return True
