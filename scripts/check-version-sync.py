"""Fail when a release-bearing component drifts from the root VERSION file."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def project_version(path: str) -> str:
    with (ROOT / path).open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def package_version(path: str) -> str:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))["version"]


versions = {
    "backend": project_version("backend/pyproject.toml"),
    "session-agent": project_version("session-agent/pyproject.toml"),
    "frontend": package_version("frontend/package.json"),
    "frontend/shared": package_version("frontend/shared/package.json"),
    "frontend/user": package_version("frontend/user/package.json"),
    "frontend/admin": package_version("frontend/admin/package.json"),
    "frontend/e2e": package_version("frontend/e2e/package.json"),
}

dockerfiles = {
    "backend image": "backend/Dockerfile",
    "session-agent image": "session-agent/Dockerfile",
    "frontend image": "frontend/Dockerfile",
    "browser image": "docker/browser/Dockerfile",
}
for component, path in dockerfiles.items():
    content = (ROOT / path).read_text(encoding="utf-8")
    match = re.search(r"^ARG OPENRBI_VERSION=(\S+)$", content, re.MULTILINE)
    versions[component] = match.group(1) if match else "<missing>"

mismatches = {component: found for component, found in versions.items() if found != EXPECTED}
if mismatches:
    for component, found in mismatches.items():
        print(f"{component}: expected {EXPECTED}, found {found}")
    raise SystemExit(1)

print(f"all release-bearing components use OpenRBI {EXPECTED}")
