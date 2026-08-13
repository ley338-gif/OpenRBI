"""AuthProvider interface (see docs/adr/0015-auth-provider-abstraction.md).

Mirrors the existing SandboxProvider pattern (session-agent/app/providers/
base.py, docs/adr/0003) — a typing.Protocol so `/auth/login` depends only on
this interface, never on a concrete verification mechanism, letting a second
auth method (LDAP, Roadmap B1.2) be added without touching the local path.

Deliberately narrow scope: a provider only answers "is this credential
valid, and which username does it belong to". Everything downstream of that
(MFA enforcement, session issuance, login lockout, audit events) stays
exactly where it already lives in app/api/auth.py's login() — those already
operate on the resolved User/Role, not on how the credential was verified,
so they apply identically regardless of which provider authenticated the
request. No behavior change for local login is intended in this file or its
first implementation (LocalAuthProvider) — see that file's own docstring.
"""

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class AuthResult:
    """Note: username is always the value the provider itself resolved the
    identity to (never blindly echoed back from the request), so a caller
    never has to trust unverified caller-supplied input for this bit.

    matched_user_id: set whenever the provider found an existing local User
    row for this username, *regardless of success* — preserves the
    pre-refactor behavior of attaching a user_id to a failed-login security
    event whenever the account exists (disabled account, wrong password),
    vs. leaving it null for a genuinely unknown username. Purely an audit
    detail, never used to bypass the generic-401 behavior the caller
    already enforces identically either way.
    """

    success: bool
    username: str | None = None
    matched_user_id: uuid.UUID | None = None
    # Populated only by LdapAuthProvider on success (Roadmap B1.3) — the
    # raw group DNs from the directory's group-membership attribute
    # (OPENRBI_LDAP_GROUP_ATTRIBUTE), for app/services/ldap_provisioning.py
    # to resolve into an OpenRBI role. None for LocalAuthProvider, which
    # has no equivalent concept — an existing local account's role is
    # already authoritative on its own User row.
    ldap_group_dns: list[str] | None = None


class AuthProvider(Protocol):
    async def authenticate(self, db: "AsyncSession", username: str, password: str) -> AuthResult: ...
    async def health(self) -> bool: ...
