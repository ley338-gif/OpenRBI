"""MIME/extension matching for MIME policy rules (docs/policies.md).

This module only answers "does this one rule's pattern match this one
candidate value." Which candidate values a rule is compared against is the
policy engine's decision (app/services/policy_engine.py): the extension and
a declared Content-Type can only make a decision stricter (DENY/QUARANTINE),
an AUTO_RELEASE rule matches the detected (magic-byte) MIME type only.
"""


def is_extension_pattern(pattern: str) -> bool:
    """A dot-prefixed pattern (`.exe`) matches file extensions, never a
    MIME type — so it can never satisfy an AUTO_RELEASE rule."""
    return pattern.strip().startswith(".")


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
