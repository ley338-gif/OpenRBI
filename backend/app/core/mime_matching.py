"""MIME/extension matching for MIME policy rules (docs/policies.md).

A file decision never rests on extension or declared Content-Type alone
(that's decided by the policy engine combining multiple signals — see
app/services/policy_engine.py); this module only answers "does this one
rule's pattern match this one candidate value."
"""


def matches_mime_pattern(value: str | None, pattern: str) -> bool:
    """`pattern` may be:
    - an exact MIME type (`application/pdf`)
    - a MIME wildcard (`application/*`, `image/*`)
    - a file extension, dot-prefixed (`.exe`), matched case-insensitively
      against `value` when `value` looks like an extension (no `/`)
    """
    if value is None:
        return False
    value = value.strip().lower()
    pattern = pattern.strip().lower()

    if pattern.startswith("."):
        return value == pattern or value.lstrip(".") == pattern.lstrip(".")

    if pattern.endswith("/*"):
        prefix = pattern[:-1]  # keep trailing "/"
        return value.startswith(prefix)

    return value == pattern
