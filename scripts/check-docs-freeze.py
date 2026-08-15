"""Release-document presence, local-link and known-stale-claim checks."""

import re
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "README.md",
    "CHANGELOG.md",
    "docs/deployment.md",
    "docs/admin-guide.md",
    "docs/user-guide.md",
    "docs/security-model.md",
    "docs/architecture.md",
    "docs/troubleshooting.md",
    "docs/supported-configurations.md",
    "docs/release/release-process.md",
    "docs/release/v1-acceptance.md",
    "docs/release/upgrade.md",
    "docs/release/rollback.md",
)
FORBIDDEN = {
    "README.md": ("Pre-alpha / MVP 1 in progress", "not yet feature-complete"),
    "docs/deployment.md": ("allow-list is hardcoded to the base `backend`",),
    "docs/security-model.md": (
        "ownership* enforcement there is still pending",
        "goes through a controlled resolver/proxy (planned",
    ),
    "docs/adr/0009-novnc-remote-display.md": ("TBD in [DEPENDENCIES.md]",),
    "DEPENDENCIES.md": ("currently just the noVNC test harness",),
}
LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def check_local_links(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    for raw_target in LINK.findall(text):
        target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
        if not target or target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        relative = unquote(target.split("#", 1)[0])
        resolved = (path.parent / relative).resolve()
        try:
            resolved.relative_to(ROOT)
        except ValueError:
            errors.append(f"{path.relative_to(ROOT)}: link escapes repository: {target}")
            continue
        if not resolved.exists():
            errors.append(f"{path.relative_to(ROOT)}: missing local link target: {target}")
    return errors


def main() -> None:
    errors: list[str] = []
    for relative in REQUIRED:
        if not (ROOT / relative).is_file():
            errors.append(f"missing required release document: {relative}")
    for relative, stale_values in FORBIDDEN.items():
        text = (ROOT / relative).read_text(encoding="utf-8")
        for stale in stale_values:
            if stale in text:
                errors.append(f"{relative}: stale release claim remains: {stale!r}")
    docs = [ROOT / "README.md", ROOT / "CHANGELOG.md", ROOT / "DEPENDENCIES.md"]
    docs.extend((ROOT / "docs").rglob("*.md"))
    for path in docs:
        errors.extend(check_local_links(path))
    if errors:
        raise SystemExit("Documentation freeze validation failed:\n- " + "\n- ".join(errors))
    print(f"PASS: documentation freeze ({len(REQUIRED)} required files; {len(docs)} files link-checked)")


if __name__ == "__main__":
    main()
