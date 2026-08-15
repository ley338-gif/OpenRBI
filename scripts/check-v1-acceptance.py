"""Fail CI if the binding v1 acceptance manifest loses required evidence."""

import re
from pathlib import Path


REQUIRED = [
    "Clean Installation",
    "Initial Admin Setup",
    "Admin MFA Enrollment",
    "Admin Login",
    "Local User Login",
    "LDAP Login",
    "LDAP Admin Mapping",
    "LDAP Invalid Password",
    "LDAP Unavailable",
    "LDAP Fail Closed",
    "Browser Session Launch",
    "Browser Session Termination",
    "Public Internet from Sandbox",
    "RFC1918 Blocked",
    "Link-local Blocked",
    "Metadata Endpoint Blocked",
    "Control Plane Blocked",
    "Benign Download",
    "Malicious/EICAR Download",
    "Scanner Unavailable",
    "Quarantine",
    "Quarantine Release",
    "Worker Drain",
    "Worker Maintenance",
    "Browser Crash Reconciliation",
    "Orphan Reconciliation",
    "Session Agent Restart",
    "Backend Restart",
    "PostgreSQL Restart",
    "Redis Restart",
    "Backup",
    "Restore",
    "Upgrade",
    "Audit Events",
    "Health Dashboard",
]
FIELDS = (
    "Preconditions",
    "Steps",
    "Expected Result",
    "Actual Result",
    "Status",
    "Evidence",
)


def main() -> None:
    path = Path("docs/release/v1-acceptance.md")
    text = path.read_text(encoding="utf-8")
    sections = re.findall(
        r"^### (\d+)\. (.+?)\n\n(.*?)(?=^### \d+\.|^## Release decision)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert len(sections) == len(REQUIRED), f"expected {len(REQUIRED)} scenarios, found {len(sections)}"
    for index, (number, title, body) in enumerate(sections, start=1):
        assert int(number) == index, f"scenario numbering jumps at {number}. {title}"
        assert title == REQUIRED[index - 1], f"unexpected scenario {number}: {title!r}"
        for field in FIELDS:
            assert f"- **{field}:**" in body, f"scenario {number} is missing {field}"
        assert "- **Status:** **PASS**" in body, f"scenario {number} is not PASS"
        evidence = re.search(r"^- \*\*Evidence:\*\* (.+)$", body, flags=re.MULTILINE)
        assert evidence and evidence.group(1).strip(), f"scenario {number} has no evidence"
    print(f"PASS: {len(sections)}/{len(REQUIRED)} required v1 acceptance scenarios are complete")


if __name__ == "__main__":
    main()
