"""Case-insensitive Distinguished Name (DN) comparison for LDAP group->role
mapping (app/services/ldap_provisioning.py).

LDAP DNs are not compared as opaque strings per RFC 4514/4517: RDN
attribute type names are always case-insensitive, and the overwhelming
majority of attribute values found in real-world DNs (cn, ou, dc, o, l,
st, c, uid) use the caseIgnoreMatch matching rule, so those are
case-insensitive too. A small number of attribute syntaxes elsewhere in
LDAP use caseExactMatch instead, but none of them are realistic DN
components (things like userPassword or a raw binary attribute) - RDN
components in practice are always caseIgnoreMatch-typed. This module
normalizes on that basis rather than pretending every possible attribute
type is covered, which the previous exact-string comparison did not do at
all - a group configured as "CN=OpenRBI-Admins,OU=Groups,DC=Example,DC=ORG"
never matched a real directory returning
"cn=openrbi-admins,ou=groups,dc=example,dc=org" for the exact same group.
"""

import ldap.dn


def normalize_dn(dn: str) -> tuple:
    """Returns a hashable, order-preserving-per-RDN-level normalized form
    of `dn` suitable for equality comparison, never for redisplay - this
    is not a re-serialization of the DN string, just a comparison key.

    RDN attribute type and value are both lowercased (caseIgnoreMatch).
    Within a single multi-valued RDN (e.g. "cn=x+ou=y"), the component
    order doesn't affect identity per the LDAP spec, so those components
    are sorted; the top-down sequence of RDNs (the actual hierarchy) is
    never reordered, since that does change identity.

    A DN that fails to parse (malformed input, e.g. from a hand-edited
    admin mapping) falls back to a plain lowercased/stripped string - it
    will then simply never match a validly-parsed DN, which is the
    correct fail-closed outcome (no privilege from an unparseable
    mapping entry) rather than raising and breaking every login.
    """
    try:
        parsed = ldap.dn.str2dn(dn)
    except ldap.DECODING_ERROR:
        return (dn.strip().lower(),)

    return tuple(
        tuple(sorted((atype.lower(), avalue.lower(), flags) for atype, avalue, flags in rdn))
        for rdn in parsed
    )


def dns_equal(a: str, b: str) -> bool:
    return normalize_dn(a) == normalize_dn(b)
