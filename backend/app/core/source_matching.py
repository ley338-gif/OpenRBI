"""Source-hostname matching for SOURCE policy rules (docs/policies.md).

Deliberately never does substring/"in" matching — that's exactly what lets
`microsoft.com.attacker.org` or `evil-microsoft.com` slip past a naive
`"microsoft.com" in hostname` check. Matching is always against whole
DNS labels.
"""

from urllib.parse import urlparse


def normalize_hostname(url_or_host: str) -> str:
    """Accepts either a bare hostname or a full URL and returns a
    lowercased hostname with any trailing dot stripped.
    """
    candidate = url_or_host.strip()
    if "://" in candidate:
        candidate = urlparse(candidate).hostname or ""
    return candidate.lower().rstrip(".")


def matches_source_pattern(hostname: str, pattern: str) -> bool:
    """`pattern` is either an exact hostname (`example.com`, matches only
    that host) or a `*.`-prefixed wildcard (`*.example.com`, matches
    `example.com` itself and any subdomain, but never a different domain
    that merely contains the string — `example.com.attacker.org` and
    `evil-example.com` both correctly do not match `*.example.com`).
    """
    host = normalize_hostname(hostname)
    pat = pattern.strip().lower().rstrip(".")

    if not pat or not host:
        return False

    if pat.startswith("*."):
        base = pat[2:]
        return host == base or host.endswith("." + base)

    return host == pat
