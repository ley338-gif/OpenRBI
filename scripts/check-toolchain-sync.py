"""Fail when the Python/Node versions CI and the dependency locks target drift
from the runtimes the shipped images actually use.

The images are the source of truth (`FROM python:X.Y` in backend/ and
session-agent/Dockerfile, `FROM node:N` in frontend/Dockerfile). A base-image
update, e.g. from Dependabot, must come with matching lockfiles
(scripts/lock-python-dependencies.sh) and CI toolchain (.github/workflows/*),
otherwise the dependency audit and the lock resolution no longer cover what
ships — exactly what happened between 1.0.1 and 1.0.2.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_DOCKERFILES = ("backend/Dockerfile", "session-agent/Dockerfile")
NODE_DOCKERFILE = "frontend/Dockerfile"
LOCK_SCRIPT = "scripts/lock-python-dependencies.sh"
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def first_match(path: str, pattern: str) -> str:
    match = re.search(pattern, (ROOT / path).read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise SystemExit(f"toolchain check: no match for {pattern!r} in {path}")
    return match.group(1)


def main() -> None:
    errors: list[str] = []

    python_versions = {path: first_match(path, r"^FROM python:(\d+\.\d+)") for path in PYTHON_DOCKERFILES}
    if len(set(python_versions.values())) != 1:
        errors.append(f"images disagree on the Python version: {python_versions}")
    runtime_python = python_versions[PYTHON_DOCKERFILES[0]]
    runtime_node = first_match(NODE_DOCKERFILE, r"^FROM node:(\d+)")

    lock_python = first_match(LOCK_SCRIPT, r'^TARGET_PYTHON="([^"]+)"')
    if lock_python != runtime_python:
        errors.append(f"{LOCK_SCRIPT} resolves for Python {lock_python}, the images run Python {runtime_python}")

    for workflow in WORKFLOWS:
        relative = workflow.relative_to(ROOT).as_posix()
        text = workflow.read_text(encoding="utf-8")
        for version in re.findall(r'python-version:\s*"?([0-9.]+)"?', text):
            if version != runtime_python:
                errors.append(f"{relative} sets up Python {version}, the images run Python {runtime_python}")
        for version in re.findall(r'node-version:\s*"?([0-9.]+)"?', text):
            if version.split(".")[0] != runtime_node:
                errors.append(f"{relative} sets up Node {version}, the frontend image builds with Node {runtime_node}")

    if errors:
        raise SystemExit("Toolchain is out of sync with the shipped images:\n- " + "\n- ".join(errors))
    print(f"PASS: toolchain matches the images (Python {runtime_python}, Node {runtime_node})")


if __name__ == "__main__":
    main()
