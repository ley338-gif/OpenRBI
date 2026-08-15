"""Real file-security probes executed inside the live backend container."""

import asyncio
import hashlib
import json
import sys
import uuid
from pathlib import Path

import app.models  # noqa: F401 - register all mapped tables
from app.config import get_settings
from app.core.security import hash_password
from app.db.session import async_session_factory
from app.models.browser_session import BrowserSession
from app.models.enums import FileAction, QuarantineStatus, ScannerStatus, SecurityEventType, SessionStatus
from app.models.incident import Incident
from app.models.quarantine import QuarantineFile
from app.models.role import Role
from app.models.security_event import SecurityEvent
from app.models.user import User
from app.services.scanning import scan_and_finalize
from sqlalchemy import delete, select

CLEAN = b"OpenRBI security release review benign file\n"
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


async def run_probe(kind: str) -> None:
    payload = EICAR if kind == "eicar" else CLEAN
    marker = uuid.uuid4().hex
    path = Path(get_settings().download_staging_dir) / f"security-review-{marker}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)

    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == "USER"))
        assert role is not None
        user = User(
            username=f"security_review_{marker}",
            password_hash=hash_password(uuid.uuid4().hex),
            role_id=role.id,
            is_active=True,
        )
        db.add(user)
        await db.flush()
        session = BrowserSession(user_id=user.id, status=SessionStatus.ACTIVE)
        db.add(session)
        await db.flush()
        item = QuarantineFile(
            session_id=session.id,
            user_id=user.id,
            original_name=f"{kind}.txt",
            extension=".txt",
            detected_mime="text/plain",
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            policy_action=FileAction.AUTO_RELEASE,
            status=QuarantineStatus.PENDING_SCAN,
            scanner_status=ScannerStatus.PENDING,
            storage_object_id=str(path),
        )
        db.add(item)
        await db.flush()
        await scan_and_finalize(db, item)
        await db.commit()
        await db.refresh(item)

        event_types = set(
            (
                await db.scalars(
                    select(SecurityEvent.event_type).where(SecurityEvent.quarantine_file_id == item.id)
                )
            ).all()
        )
        incident_count = len(
            (await db.scalars(select(Incident.id).where(Incident.quarantine_file_id == item.id))).all()
        )
        if kind == "clean":
            assert item.status == QuarantineStatus.RELEASED
            assert item.scanner_status == ScannerStatus.CLEAN
            assert SecurityEventType.FILE_RELEASED in event_types
        elif kind == "eicar":
            assert item.status == QuarantineStatus.QUARANTINED
            assert item.scanner_status == ScannerStatus.INFECTED
            assert SecurityEventType.MALWARE_DETECTED in event_types
            assert incident_count == 1
        elif kind == "outage":
            assert item.status == QuarantineStatus.QUARANTINED
            assert item.scanner_status == ScannerStatus.ERROR
            assert SecurityEventType.DOWNLOAD_BLOCKED in event_types
            assert SecurityEventType.FILE_RELEASED not in event_types
        else:
            raise ValueError(f"unknown probe: {kind}")

        print(
            json.dumps(
                {
                    "probe": kind,
                    "status": item.status.value,
                    "scanner_status": item.scanner_status.value,
                    "sha256": item.sha256,
                    "events": sorted(event.value for event in event_types),
                    "incidents": incident_count,
                },
                sort_keys=True,
            )
        )

        await db.execute(delete(SecurityEvent).where(SecurityEvent.quarantine_file_id == item.id))
        await db.execute(delete(Incident).where(Incident.quarantine_file_id == item.id))
        await db.execute(delete(QuarantineFile).where(QuarantineFile.id == item.id))
        await db.execute(delete(BrowserSession).where(BrowserSession.id == session.id))
        await db.execute(delete(User).where(User.id == user.id))
        await db.commit()
    path.unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: security-release-review.py <clean|eicar|outage>")
    asyncio.run(run_probe(sys.argv[1]))
