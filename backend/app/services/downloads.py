import hashlib
import os

import magic
from sqlalchemy import select

from app.config import get_settings
from app.core import session_agent_client
from app.core.session_agent_client import SessionAgentError
from app.core.source_matching import normalize_hostname
from app.models.browser_session import BrowserSession
from app.models.enums import QuarantineStatus, ScannerStatus, SecurityEventType
from app.models.quarantine import QuarantineFile
from app.services.policy_engine import FileDecisionInput, evaluate_file_action
from app.services.scanning import scan_and_finalize
from app.services.security_events import record_security_event


def _stage_file(data: bytes, sha256: str) -> str:
    """Interim local staging (Phase 13) — content-addressed by hash so two
    identical downloads don't collide and a filename is never used as a
    storage key (docs/quarantine.md: quarantined files are never stored
    under their original name). Replaced by real quarantine storage in
    Phase 15.
    """
    settings = get_settings()
    os.makedirs(settings.download_staging_dir, exist_ok=True)
    path = os.path.join(settings.download_staging_dir, sha256)
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(data)
    return path


async def process_new_downloads(db, session: BrowserSession) -> list[QuarantineFile]:
    """Polls the sandbox's download directory (via the Session Agent —
    docs/adr/0005, the backend never reaches into the sandbox filesystem or
    network directly) for newly completed downloads and stages each one:
    hash, size, detected MIME (magic bytes, never trusting the extension
    alone), best-effort origin URL, a policy pre-check
    (app/services/policy_engine.py), and a real ClamAV scan with a
    fail-closed final decision (app/services/scanning.py). The actual
    single-use download token for user retrieval of a RELEASED file, and
    the admin release/reject workflow for a QUARANTINED one, are Phase 15.
    """
    try:
        files = await session_agent_client.list_downloads(str(session.id))
    except SessionAgentError:
        return []  # sandbox not reachable right now; try again next poll

    created: list[QuarantineFile] = []
    for entry in files:
        try:
            data, origin_url = await session_agent_client.fetch_download(str(session.id), entry.filename)
        except SessionAgentError:
            continue  # transient fetch failure; file stays in the sandbox, retried next poll

        sha256 = hashlib.sha256(data).hexdigest()

        # If a prior poll fetched this same content but failed to delete it
        # from the sandbox (best-effort cleanup below), don't create a
        # second QuarantineFile row for it — just retry the delete.
        existing = await db.execute(
            select(QuarantineFile.id).where(
                QuarantineFile.session_id == session.id, QuarantineFile.sha256 == sha256
            )
        )
        if existing.scalar_one_or_none() is not None:
            try:
                await session_agent_client.delete_download(str(session.id), entry.filename)
            except SessionAgentError:
                pass
            continue

        detected_mime = magic.from_buffer(data, mime=True)
        extension = os.path.splitext(entry.filename)[1] or None
        source_hostname = normalize_hostname(origin_url) if origin_url else None

        decision = await evaluate_file_action(
            db,
            session.user_id,
            FileDecisionInput(
                declared_mime=None,  # not exposed by the filesystem-based detection method used here
                detected_mime=detected_mime,
                extension=extension,
                size_bytes=len(data),
                source_hostname=source_hostname,
            ),
        )

        storage_object_id = _stage_file(data, sha256)

        quarantine_file = QuarantineFile(
            session_id=session.id,
            user_id=session.user_id,
            original_name=entry.filename,
            extension=extension,
            declared_mime=None,
            detected_mime=detected_mime,
            size_bytes=len(data),
            sha256=sha256,
            initial_url=origin_url,
            final_url=origin_url,
            source_host=source_hostname,
            redirect_chain=None,
            tls_used=origin_url.startswith("https://") if origin_url else None,
            scanner_status=ScannerStatus.PENDING,
            policy_action=decision.action,
            policy_version_id=decision.policy_version_id,
            status=QuarantineStatus.PENDING_SCAN,
            storage_object_id=storage_object_id,
        )
        db.add(quarantine_file)
        await db.flush()

        await record_security_event(
            db,
            SecurityEventType.DOWNLOAD_REQUESTED,
            user_id=session.user_id,
            session_id=session.id,
            quarantine_file_id=quarantine_file.id,
            metadata={"sha256": sha256, "detected_mime": detected_mime, "policy_action": decision.action.value},
        )
        await scan_and_finalize(db, quarantine_file)
        created.append(quarantine_file)

        try:
            await session_agent_client.delete_download(str(session.id), entry.filename)
        except SessionAgentError:
            pass  # best-effort cleanup; a leftover file is just re-processed (deduped by sha256) next poll

    if created:
        await db.commit()
    return created
