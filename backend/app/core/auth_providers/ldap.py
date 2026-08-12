"""LdapAuthProvider — second AuthProvider implementation (Roadmap Phase B /
B1.2, docs/adr/0015). Scope is deliberately narrow: verify a username/
password pair against a real LDAP/LDAPS bind. Group-to-role mapping and
wiring this into /auth/login's actual flow (including just-in-time local
account provisioning) is Roadmap B1.3/B1.4, kept separate on purpose.

Two-step bind, standard for directory authentication and required here
specifically because a user's own password is never cached or compared
locally (Roadmap B1's explicit prohibition):
  1. Bind as a dedicated search/service account, look up the user's DN by
     username.
  2. Bind again, this time *as that DN with the password the caller
     supplied* — this second bind succeeding or failing is the actual
     credential verification. Nothing here ever inspects or stores the
     user's real password beyond passing it straight into this bind call.

Fail-closed (docs/adr/0008-fail-closed.md, restated for this provider in
docs/adr/0015): any connection failure, TLS failure, or unexpected LDAP
error results in AuthResult(success=False) — the same outward shape as a
wrong password, never a fallback to some other outcome that grants access.
"""

import ldap
import ldap.filter

from app.config import get_settings
from app.core.auth_providers.base import AuthResult


class LdapAuthProvider:
    def __init__(self) -> None:
        self._settings = get_settings()

    def _new_connection(self) -> "ldap.ldapobject.LDAPObject":
        conn = ldap.initialize(self._settings.ldap_server_uri)
        conn.set_option(ldap.OPT_REFERRALS, 0)
        conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 5.0)
        conn.set_option(ldap.OPT_TIMEOUT, 5.0)
        # Config-load-time validation (app/config.py) already refuses to
        # start with a plain ldap:// URI and StartTLS disabled — this is
        # the enforcement side of that decision, not a second place the
        # choice could be made differently.
        if self._settings.ldap_server_uri.startswith("ldap://") and self._settings.ldap_use_starttls:
            conn.start_tls_s()
        return conn

    async def authenticate(self, db, username: str, password: str) -> AuthResult:  # noqa: ARG002 - db unused, kept for AuthProvider protocol parity
        if not password:
            # An empty password against some directories is treated as an
            # anonymous bind, which "succeeds" without checking anything —
            # reject before ever opening a connection, not after.
            return AuthResult(success=False)

        try:
            search_conn = self._new_connection()
            search_conn.simple_bind_s(self._settings.ldap_bind_dn, self._settings.ldap_bind_password)

            escaped_username = ldap.filter.escape_filter_chars(username)
            search_filter = self._settings.ldap_user_search_filter.format(username=escaped_username)
            results = search_conn.search_s(
                self._settings.ldap_base_dn,
                ldap.SCOPE_SUBTREE,
                search_filter,
                [self._settings.ldap_group_attribute],
            )
            search_conn.unbind_s()

            # Excludes referral entries (dn is None) — real user entries only.
            user_entries = [(dn, attrs) for dn, attrs in results if dn is not None]
            if len(user_entries) != 1:
                # Zero matches: unknown username. More than one: an
                # ambiguous search filter/base DN is a configuration
                # problem, not something to guess at by picking the first
                # result — fail closed either way.
                return AuthResult(success=False)
            user_dn, attrs = user_entries[0]

            user_conn = self._new_connection()
            try:
                user_conn.simple_bind_s(user_dn, password)
            except ldap.INVALID_CREDENTIALS:
                return AuthResult(success=False)
            finally:
                user_conn.unbind_s()

            return AuthResult(success=True, username=username)

        except (ldap.SERVER_DOWN, ldap.CONNECT_ERROR, ldap.TIMEOUT, ldap.LDAPError):
            # Deliberately broad: any LDAP-layer failure not already
            # handled above (server unreachable, TLS handshake failure,
            # malformed response, ...) is fail-closed, not a bypass.
            return AuthResult(success=False)

    async def health(self) -> bool:
        try:
            conn = self._new_connection()
            conn.simple_bind_s(self._settings.ldap_bind_dn, self._settings.ldap_bind_password)
            conn.unbind_s()
            return True
        except ldap.LDAPError:
            return False
