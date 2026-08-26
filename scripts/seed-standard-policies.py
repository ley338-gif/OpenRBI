"""Seeds a set of standard/template policies, using the same real service
functions the Admin Portal itself calls (app/services/policies.py) — never
a hand-rolled INSERT.

Every policy is created as a DRAFT and immediately published (so it's
visible and usable as a template right away), but deliberately left
UNATTACHED to any group — attaching a policy is what actually makes it
take effect for real users (app/services/policy_engine.py only ever
resolves policies through GroupPolicy), so nothing here changes behavior
for anyone until an admin deliberately attaches one of these to a group
via the Admin Portal (Policies -> a policy -> assign to group).

Idempotent: re-running skips any policy whose name already exists rather
than erroring out, so this is safe to run again after adding a new
template to STANDARD_POLICIES below.

Run inside the backend container (see scripts/seed-standard-policies.sh):
    docker exec openrbi-backend-1 python /app/seed_standard_policies.py
"""

import asyncio
import json

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.role import Role
from app.models.user import User
from app.services.policies import PolicyServiceError, create_draft_version, create_policy, publish_version

# Real-world MIME types for the OOXML formats (docs/policies.md's own
# examples use exactly this style: an exact type, or a dot-prefixed
# extension as a fallback when a declared/detected MIME type is missing or
# generic — matches_mime_pattern() (app/core/mime_matching.py) checks the
# declared MIME, the scanner-detected MIME, and the extension, so either
# form catches a real file).
_OFFICE_MIME_TYPES = [
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
]

# Executables are frequently mislabeled or missing a declared Content-Type
# entirely, so these rules lean on the extension fallback rather than a
# MIME type — matches_mime_pattern() checks it as a third, independent
# signal alongside declared/detected MIME (never the sole check upstream,
# see that module's docstring).
_EXECUTABLE_EXTENSIONS = [".exe", ".msi", ".bat", ".cmd", ".ps1", ".sh", ".com", ".scr"]

STANDARD_POLICIES: list[dict] = [
    {
        "name": "PDF Only",
        "policy_type": "MIME",
        "description": (
            "Only PDF files are auto-released. Everything else falls through to the "
            "engine's fail-closed default (QUARANTINE, not DENY) — held for review "
            "rather than silently dropped."
        ),
        "content": {},
        "file_rules": [
            {"rule_type": "MIME", "match_pattern": "application/pdf", "action": "AUTO_RELEASE"},
        ],
    },
    {
        "name": "Office Documents",
        "policy_type": "MIME",
        "description": "PDF and modern Office formats (.docx/.xlsx/.pptx) are auto-released.",
        "content": {},
        "file_rules": [
            {"rule_type": "MIME", "match_pattern": mime, "action": "AUTO_RELEASE"} for mime in _OFFICE_MIME_TYPES
        ],
    },
    {
        "name": "Images Only",
        "policy_type": "MIME",
        "description": "Any image/* MIME type is auto-released.",
        "content": {},
        "file_rules": [
            {"rule_type": "MIME", "match_pattern": "image/*", "action": "AUTO_RELEASE"},
        ],
    },
    {
        "name": "Block Executables",
        "policy_type": "MIME",
        "description": (
            "Hard DENY for common executable/script extensions, regardless of what any "
            "other group policy allows — DENY outranks QUARANTINE and AUTO_RELEASE in "
            "the engine's conflict resolution (docs/policies.md)."
        ),
        "content": {},
        "file_rules": [
            {"rule_type": "MIME", "match_pattern": ext, "action": "DENY"} for ext in _EXECUTABLE_EXTENSIONS
        ],
    },
    {
        "name": "Full HD",
        "policy_type": "SESSION",
        "description": "1920x1080 browser sandbox resolution.",
        "content": {"screen_width": 1920, "screen_height": 1080},
        "file_rules": [],
    },
    {
        "name": "Low Resolution",
        "policy_type": "SESSION",
        "description": "1280x720 browser sandbox resolution — lower bandwidth/resource use.",
        "content": {"screen_width": 1280, "screen_height": 720},
        "file_rules": [],
    },
    {
        "name": "No Clipboard",
        "policy_type": "CLIPBOARD",
        "description": "Blocks clipboard transfer in both directions between the local machine and the sandbox.",
        "content": {"clipboard_mode": "NONE"},
        "file_rules": [],
    },
]


async def main() -> None:
    async with async_session_factory() as db:
        result = await db.execute(
            select(User).join(Role, User.role_id == Role.id).where(Role.name == "ADMIN").order_by(User.created_at).limit(1)
        )
        actor = result.scalar_one_or_none()
        if actor is None:
            raise SystemExit(
                "No ADMIN user exists yet — bootstrap the system (POST /setup/admin, or "
                "the Admin Portal's first-run wizard) before seeding standard policies."
            )

        created, skipped = [], []
        for spec in STANDARD_POLICIES:
            try:
                policy = await create_policy(
                    db, name=spec["name"], policy_type=spec["policy_type"], actor_id=actor.id,
                    description=spec["description"],
                )
            except PolicyServiceError:
                skipped.append(spec["name"])
                continue

            version = await create_draft_version(
                db, policy, content=spec["content"], file_rules=spec["file_rules"], actor_id=actor.id,
            )
            await publish_version(db, policy, version, actor_id=actor.id)
            created.append(spec["name"])

        await db.commit()
        print(json.dumps({"created": created, "skipped_already_exists": skipped}))


if __name__ == "__main__":
    asyncio.run(main())
