"""Standard policy templates (docs/policies.md#standard-policy-templates).

Created as published but UNATTACHED policies, through the same service
functions the Admin Portal calls: a policy only takes effect once an admin
attaches it to a group (app/services/policy_engine.py resolves policies
exclusively through GroupPolicy), so seeding never changes what any user's
session may do.

Seeded automatically when first-run setup completes (setup_service) and on
every `scripts/deploy.sh` run (so an update brings in templates added in
newer releases). Each template name is recorded in
SystemState.seeded_policy_templates the first time it is handled and is
never touched again after that: an admin who renames, edits or archives a
template does not get the original back on the next update.

Templates are system-authored (no actor, created_by NULL): they come with
the product rather than from any one admin, and a later cleanup of that
admin's account never trips over a foreign key.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.policy import Policy
from app.models.system_state import SYSTEM_STATE_ID, SystemState
from app.services.policies import create_draft_version, create_policy, publish_version

# Real-world MIME types for the OOXML formats. AUTO_RELEASE rules must use
# MIME types: the policy engine (app/services/policy_engine.py) only lets a
# file's detected (magic-byte) MIME type satisfy an AUTO_RELEASE rule, never
# its extension or declared Content-Type.
_OFFICE_MIME_TYPES = [
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
]

# DENY rules may match on the extension (it can only make a decision
# stricter), which catches executables by name. The detected MIME types
# below catch them when renamed (e.g. an .exe saved as report.pdf) — the
# values libmagic reports for PE, DOS, MSI, ELF, Mach-O and script files.
_EXECUTABLE_EXTENSIONS = [".exe", ".msi", ".bat", ".cmd", ".ps1", ".sh", ".com", ".scr"]
_EXECUTABLE_MIME_TYPES = [
    "application/vnd.microsoft.portable-executable",
    "application/x-dosexec",
    "application/x-msdownload",
    "application/x-msi",
    "application/x-executable",
    "application/x-pie-executable",
    "application/x-sharedlib",
    "application/x-mach-binary",
    "text/x-shellscript",
    "text/x-msdos-batch",
]

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
            "Hard DENY for common executable/script extensions and for files detected as "
            "executables even when renamed, regardless of what any other group policy "
            "allows — DENY outranks QUARANTINE and AUTO_RELEASE in the engine's conflict "
            "resolution (docs/policies.md)."
        ),
        "content": {},
        "file_rules": [
            {"rule_type": "MIME", "match_pattern": pattern, "action": "DENY"}
            for pattern in _EXECUTABLE_EXTENSIONS + _EXECUTABLE_MIME_TYPES
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


async def seed_standard_policies(db: AsyncSession) -> tuple[list[str], list[str]]:
    """Creates every template not yet recorded as seeded. Returns
    (created, skipped); a template is skipped (and recorded) when a policy
    with its name already exists, e.g. one created by the pre-deploy.sh
    seed script or by an admin. Flushes but does not commit.
    """
    result = await db.execute(select(SystemState).where(SystemState.id == SYSTEM_STATE_ID).with_for_update())
    state = result.scalar_one_or_none()
    if state is None:
        raise RuntimeError("system_state row missing; complete first-run setup before seeding policies")

    seeded = set(state.seeded_policy_templates or [])
    created: list[str] = []
    skipped: list[str] = []
    for spec in STANDARD_POLICIES:
        if spec["name"] in seeded:
            continue
        exists = await db.execute(select(Policy.id).where(Policy.name == spec["name"]))
        if exists.first() is not None:
            skipped.append(spec["name"])
        else:
            policy = await create_policy(
                db, name=spec["name"], policy_type=spec["policy_type"], actor_id=None,
                description=spec["description"],
            )
            version = await create_draft_version(
                db, policy, content=spec["content"], file_rules=spec["file_rules"], actor_id=None,
            )
            await publish_version(db, policy, version, actor_id=None)
            created.append(spec["name"])
        seeded.add(spec["name"])

    # A new list object, so SQLAlchemy sees the JSONB column as changed.
    state.seeded_policy_templates = sorted(seeded)
    db.add(state)
    await db.flush()
    return created, skipped
