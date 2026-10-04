"""Release-document presence, local-link/anchor and known-stale-claim checks."""

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
    "README.md": (
        "Pre-alpha / MVP 1 in progress",
        "not yet feature-complete",
        "MVP 1 goals",
    ),
    "SECURITY.md": ("Known MVP limitations",),
    "docs/deployment.md": ("allow-list is hardcoded to the base `backend`",),
    "docs/security-model.md": (
        "ownership* enforcement there is still pending",
        "goes through a controlled resolver/proxy (planned",
    ),
    "docs/adr/0009-novnc-remote-display.md": ("TBD in [DEPENDENCIES.md]",),
    "DEPENDENCIES.md": ("currently just the noVNC test harness",),
}
LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HTML_ANCHOR = re.compile(r"<a\s[^>]*\b(?:id|name)=[\"']([^\"']+)[\"']", re.IGNORECASE)


def github_slug(heading: str) -> str:
    """The anchor GitHub generates for a heading: the rendered text,
    lowercased, with everything but letters, digits, `_`, `-` and spaces
    dropped and spaces turned into `-`. Code spans keep their text verbatim
    (underscores included); emphasis markers, link targets and HTML tags are
    not part of the rendered text.
    """
    parts = re.split(r"(`+[^`]*`+)", heading)
    text = []
    for part in parts:
        if part.startswith("`"):
            text.append(part.strip("`"))
            continue
        part = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", part)
        part = re.sub(r"<[^>]+>", "", part)
        part = part.replace("*", "")
        part = re.sub(r"(?<!\w)_+|_+(?!\w)", "", part)
        text.append(part)
    slug = re.sub(r"[^\w\- ]", "", "".join(text).strip().lower())
    return slug.replace(" ", "-")


_ANCHORS: dict[Path, set[str]] = {}


def anchors(path: Path) -> set[str]:
    """Every fragment a Markdown file answers to: heading slugs (duplicates
    get GitHub's `-1`, `-2`, ... suffix) plus explicit `<a id/name>` anchors.
    Headings inside fenced code blocks don't count.
    """
    if path not in _ANCHORS:
        found: set[str] = set()
        seen: dict[str, int] = {}
        fence: str | None = None
        for line in path.read_text(encoding="utf-8").splitlines():
            marker = FENCE.match(line)
            if marker:
                if fence is None:
                    fence = marker.group(1)[0] * 3
                elif marker.group(1).startswith(fence):
                    fence = None
                continue
            if fence is not None:
                continue
            found.update(HTML_ANCHOR.findall(line))
            heading = HEADING.match(line)
            if heading:
                slug = github_slug(heading.group(2))
                count = seen.get(slug, 0)
                seen[slug] = count + 1
                found.add(slug if count == 0 else f"{slug}-{count}")
        _ANCHORS[path] = found
    return _ANCHORS[path]


def check_local_links(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    for raw_target in LINK.findall(text):
        target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        relative, _, fragment = target.partition("#")
        relative = unquote(relative)
        resolved = (path.parent / relative).resolve() if relative else path
        try:
            resolved.relative_to(ROOT)
        except ValueError:
            errors.append(f"{path.relative_to(ROOT)}: link escapes repository: {target}")
            continue
        if not resolved.exists():
            errors.append(f"{path.relative_to(ROOT)}: missing local link target: {target}")
            continue
        if fragment and resolved.suffix == ".md" and unquote(fragment) not in anchors(resolved):
            errors.append(f"{path.relative_to(ROOT)}: missing anchor: {target}")
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
    docs = sorted(ROOT.glob("*.md"))
    docs.extend(ROOT / relative for relative in ("frontend/README.md",))
    docs.extend(sorted((ROOT / "docs").rglob("*.md")))
    for path in docs:
        errors.extend(check_local_links(path))
    if errors:
        raise SystemExit("Documentation freeze validation failed:\n- " + "\n- ".join(errors))
    print(f"PASS: documentation freeze ({len(REQUIRED)} required files; {len(docs)} files link-checked)")


if __name__ == "__main__":
    main()
