"""LdapAuthProvider — second AuthProvider implementation (Roadmap Phase B /
B1.2, docs/adr/0015). Scope is deliberately narrow: verify a username/
password pair against a real LDAP/LDAPS bind. Group-to-role mapping and
wiring this into /auth/login's actual flow (including just-in-time local
account provisioning) is Roadmap B1.3/B1.4.

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

Roadmap B1.8 adds test_connection(): the admin portal's "Test LDAP
configuration" feature (docs/adr/0016) deliberately reuses this exact
class and its exact connection/bind logic instead of a second LDAP client
— the test result is only meaningful if it exercises the identical code
path a real login would.
"""

import os
from dataclasses import dataclass, field

from app.config import get_settings

# RBI-POST-001: these must be set before `import ldap` below, not merely
# before any connection is opened. In testing, python-ldap's underlying
# OpenLDAP C library reads LDAPTLS_REQCERT/LDAPTLS_CACERT once, at import/
# first-load time — an os.environ mutation made later at connection time
# (even before ldap.initialize()) was silently ignored, with TLS
# certificate verification falling back to whatever was in the
# environment at import instead. "demand" is a fixed, unconditional
# policy — there is no setting anywhere that weakens it. ca_cert_file is
# itself a single deployment-wide value (OPENRBI_LDAP_CA_CERT_FILE) fixed
# for the lifetime of this process, so reading it once here, at the only
# point that's actually reliable, is correct — not merely a workaround.
os.environ["LDAPTLS_REQCERT"] = "demand"
_ca_cert_file = get_settings().ldap_ca_cert_file
if _ca_cert_file:
    os.environ["LDAPTLS_CACERT"] = _ca_cert_file

import ldap  # noqa: E402 - see comment above; must follow the LDAPTLS_* env setup
import ldap.filter  # noqa: E402

from app.core.auth_providers.base import AuthResult


@dataclass
class LdapConnectionConfig:
    """Everything LdapAuthProvider needs, decoupled from *where* it came
    from — app/config.py's env-var-backed Settings for the pre-B1.8 path,
    or app/services/ldap_config_service.py's DB-backed effective config
    for B1.8. Both construct this the same way, so LdapAuthProvider itself
    doesn't need to know or care which one it's talking to.
    """

    server_uri: str
    use_starttls: bool
    bind_dn: str
    bind_password: str
    base_dn: str
    user_search_filter: str
    group_attribute: str


@dataclass
class LdapTestStep:
    name: str
    ok: bool
    detail: str | None = None


@dataclass
class LdapTestResult:
    """success reflects only the steps required to trust this config for
    real logins (connection, TLS, service bind, search base) — the
    optional user-search/group-resolution probe (only run if a
    test_username was supplied) is informational and never blocks
    activation on its own, since a typo'd probe username says nothing
    about whether the underlying configuration is correct.
    """

    steps: list[LdapTestStep] = field(default_factory=list)
    success: bool = False
    groups_discovered: int | None = None


def _friendly_ldap_error(exc: Exception) -> str:
    """Never surfaces exc.args verbatim to an API response — python-ldap's
    own diagnostic strings are usually safe (server-provided protocol
    text, not credentials), but a hand-picked set of known-common causes
    reads better for an admin than any raw exception text, stack trace
    included. Full exception details still go to the server-side log
    (the caller logs exc itself, this function only prettifies what goes
    in the HTTP response) — see app/api/admin_ldap.py.
    """
    text = str(exc).lower()
    if "certificate" in text or "tls" in text or "ssl" in text:
        return "TLS certificate validation failed"
    if isinstance(exc, ldap.INVALID_CREDENTIALS):
        return "Invalid bind credentials"
    if isinstance(exc, ldap.NO_SUCH_OBJECT):
        return "Base DN not found on the server"
    if isinstance(exc, (ldap.SERVER_DOWN, ldap.CONNECT_ERROR)):
        return "Could not reach the LDAP server (check host, port, and network path)"
    if isinstance(exc, ldap.TIMEOUT):
        return "Connection timed out"
    return f"LDAP error ({type(exc).__name__})"


class LdapAuthProvider:
    def __init__(self, config: LdapConnectionConfig) -> None:
        self._config = config

    def _new_connection(self) -> "ldap.ldapobject.LDAPObject":
        # RBI-POST-001: certificate verification must be explicit, not an
        # implicit OpenLDAP-/Debian-default that a differently-configured
        # host or library upgrade could silently change out from under us.
        # "demand" fails the handshake (and therefore the whole bind) on
        # any missing/invalid/untrusted server certificate — there is
        # deliberately no code path that sets a weaker value. If
        # ca_cert_file is set, it's an *additional* trust anchor (an
        # internal/private CA) layered on top of the OS trust store, never
        # a replacement for it.
        #
        # Actual enforcement is the module-level LDAPTLS_REQCERT/
        # LDAPTLS_CACERT setup above, applied once at import time — see
        # that comment for why it can't be done reliably here, per
        # connection, at all.
        conn = ldap.initialize(self._config.server_uri)
        conn.set_option(ldap.OPT_REFERRALS, 0)
        conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 5.0)
        conn.set_option(ldap.OPT_TIMEOUT, 5.0)

        # Config-load-time validation (app/config.py, and app/services/
        # ldap_config_service.py for the DB-backed path) already refuses a
        # plain ldap:// URI with StartTLS disabled — this is the
        # enforcement side of that decision, not a second place the choice
        # could be made differently.
        if self._config.server_uri.startswith("ldap://") and self._config.use_starttls:
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
            search_conn.simple_bind_s(self._config.bind_dn, self._config.bind_password)

            escaped_username = ldap.filter.escape_filter_chars(username)
            search_filter = self._config.user_search_filter.format(username=escaped_username)
            results = search_conn.search_s(
                self._config.base_dn,
                ldap.SCOPE_SUBTREE,
                search_filter,
                [self._config.group_attribute],
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

            raw_groups = attrs.get(self._config.group_attribute, [])
            group_dns = [g.decode("utf-8") if isinstance(g, bytes) else g for g in raw_groups]
            return AuthResult(success=True, username=username, ldap_group_dns=group_dns)

        except (ldap.SERVER_DOWN, ldap.CONNECT_ERROR, ldap.TIMEOUT, ldap.LDAPError):
            # Deliberately broad: any LDAP-layer failure not already
            # handled above (server unreachable, TLS handshake failure,
            # malformed response, ...) is fail-closed, not a bypass.
            return AuthResult(success=False)

    async def health(self) -> bool:
        try:
            conn = self._new_connection()
            conn.simple_bind_s(self._config.bind_dn, self._config.bind_password)
            conn.unbind_s()
            return True
        except ldap.LDAPError:
            return False

    async def test_connection(self, test_username: str | None = None) -> LdapTestResult:
        result = LdapTestResult()

        try:
            conn = self._new_connection()
        except ldap.LDAPError as exc:
            result.steps.append(LdapTestStep("TLS / connection", False, _friendly_ldap_error(exc)))
            return result
        result.steps.append(LdapTestStep("TLS / connection", True))

        try:
            conn.simple_bind_s(self._config.bind_dn, self._config.bind_password)
        except ldap.LDAPError as exc:
            result.steps.append(LdapTestStep("Service bind", False, _friendly_ldap_error(exc)))
            return result
        result.steps.append(LdapTestStep("Service bind", True))

        try:
            conn.search_s(self._config.base_dn, ldap.SCOPE_BASE, "(objectClass=*)")
        except ldap.LDAPError as exc:
            result.steps.append(LdapTestStep("Search base", False, _friendly_ldap_error(exc)))
            conn.unbind_s()
            return result
        result.steps.append(LdapTestStep("Search base", True))

        # Everything required for a real login to work has now passed.
        result.success = True

        if test_username:
            try:
                escaped_username = ldap.filter.escape_filter_chars(test_username)
                search_filter = self._config.user_search_filter.format(username=escaped_username)
                results = conn.search_s(
                    self._config.base_dn, ldap.SCOPE_SUBTREE, search_filter, [self._config.group_attribute]
                )
                user_entries = [(dn, attrs) for dn, attrs in results if dn is not None]
                if len(user_entries) != 1:
                    result.steps.append(
                        LdapTestStep(
                            "User search",
                            False,
                            f"Expected exactly one match for '{test_username}', found {len(user_entries)}",
                        )
                    )
                else:
                    result.steps.append(LdapTestStep("User search", True))
                    _, attrs = user_entries[0]
                    raw_groups = attrs.get(self._config.group_attribute, [])
                    result.groups_discovered = len(raw_groups)
                    result.steps.append(
                        LdapTestStep("Group resolution", True, f"{result.groups_discovered} group(s) discovered")
                    )
            except ldap.LDAPError as exc:
                result.steps.append(LdapTestStep("User search", False, _friendly_ldap_error(exc)))

        conn.unbind_s()
        return result
