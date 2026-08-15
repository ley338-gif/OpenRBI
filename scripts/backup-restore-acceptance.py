"""Seed, corrupt, and verify state for the v1 backup/restore acceptance gate."""

import asyncio
import hashlib
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

import app.models  # noqa: F401 - registers every mapped table with Base
from app.db.base import Base
from app.db.session import async_session_factory
from app.models.browser_session import BrowserSession
from app.models.enums import (
    FileAction,
    QuarantineStatus,
    ScannerStatus,
    SecurityEventType,
    SessionStatus,
)
from app.models.policy import Policy
from app.models.quarantine import QuarantineFile
from app.models.security_event import SecurityEvent
from app.models.user import User
from app.services.policies import create_draft_version, create_policy, publish_version
from app.services.security_events import record_security_event
from sqlalchemy import select, text

ADMIN_USERNAME = "acceptance_admin"
USER_USERNAME = "acceptance_user"
USER_PASSWORD = "Acceptance-User-Password-2026!"
POLICY_NAME = "backup-restore-acceptance-policy"
ORIGINAL_NAME = "backup-restore-evidence.txt"
PAYLOAD = b"OpenRBI v1 backup/restore quarantine evidence\n"
STAGING_DIR = Path("/app/data/staging")
BASE = "http://localhost:8000"


async def table_counts(db) -> dict[str, int]:
    counts = {}
    for table in sorted(Base.metadata.tables):
        counts[table] = int(await db.scalar(text(f'SELECT count(*) FROM "{table}"')) or 0)
    return counts


async def seed(manifest_path: Path) -> None:
    sha256 = hashlib.sha256(PAYLOAD).hexdigest()
    storage_path = STAGING_DIR / sha256
    async with async_session_factory() as db:
        admin = await db.scalar(select(User).where(User.username == ADMIN_USERNAME))
        user = await db.scalar(select(User).where(User.username == USER_USERNAME))
        assert admin is not None and user is not None

        policy = await create_policy(
            db,
            name=POLICY_NAME,
            policy_type="MIME",
            actor_id=admin.id,
            description="v1 backup/restore acceptance evidence",
        )
        version = await create_draft_version(
            db,
            policy,
            content={"acceptance_marker": "v1-009"},
            file_rules=[
                {
                    "rule_type": "MIME",
                    "match_pattern": "text/plain",
                    "action": "QUARANTINE",
                    "priority": 10,
                }
            ],
            actor_id=admin.id,
        )
        await publish_version(db, policy, version, actor_id=admin.id)

        session = BrowserSession(
            user_id=user.id,
            status=SessionStatus.TERMINATED,
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
        )
        db.add(session)
        await db.flush()

        STAGING_DIR.mkdir(parents=True, exist_ok=True)
        storage_path.write_bytes(PAYLOAD)
        quarantine = QuarantineFile(
            session_id=session.id,
            user_id=user.id,
            original_name=ORIGINAL_NAME,
            extension=".txt",
            declared_mime="text/plain",
            detected_mime="text/plain",
            size_bytes=len(PAYLOAD),
            sha256=sha256,
            initial_url="https://backup-restore.invalid/evidence.txt",
            final_url="https://backup-restore.invalid/evidence.txt",
            source_host="backup-restore.invalid",
            redirect_chain=[],
            tls_used=True,
            scanner_status=ScannerStatus.CLEAN,
            scanner_result="acceptance fixture: clean",
            policy_action=FileAction.QUARANTINE,
            policy_version_id=version.id,
            status=QuarantineStatus.QUARANTINED,
            storage_object_id=str(storage_path),
        )
        db.add(quarantine)
        await db.flush()
        event = await record_security_event(
            db,
            SecurityEventType.FILE_QUARANTINED,
            user_id=user.id,
            session_id=session.id,
            quarantine_file_id=quarantine.id,
            metadata={"acceptance_marker": "v1-009", "sha256": sha256},
        )
        await db.commit()

        manifest = {
            "counts": await table_counts(db),
            "user_id": str(user.id),
            "policy_id": str(policy.id),
            "policy_version_id": str(version.id),
            "session_id": str(session.id),
            "quarantine_id": str(quarantine.id),
            "security_event_id": str(event.id),
            "sha256": sha256,
            "storage_path": str(storage_path),
        }
        manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    print("ACCEPT BR-01 realistic users, published policy, audit event, and quarantine object seeded")
    print(f"BASELINE COUNTS {json.dumps(manifest['counts'], sort_keys=True)}")


async def corrupt(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    async with async_session_factory() as db:
        await db.execute(
            text("UPDATE users SET username = 'v1-009-corrupted-user' WHERE id = :id"),
            {"id": uuid.UUID(manifest["user_id"])},
        )
        await db.execute(
            text("UPDATE policies SET name = 'v1-009-corrupted-policy' WHERE id = :id"),
            {"id": uuid.UUID(manifest["policy_id"])},
        )
        await db.execute(
            text("DELETE FROM security_events WHERE id = :id"),
            {"id": uuid.UUID(manifest["security_event_id"])},
        )
        await db.execute(
            text("DELETE FROM quarantine_files WHERE id = :id"),
            {"id": uuid.UUID(manifest["quarantine_id"])},
        )
        await db.commit()
    Path(manifest["storage_path"]).write_bytes(b"corrupted after backup\n")
    print("ACCEPT BR-04 database rows and quarantine bytes deliberately corrupted after backup")


async def verify_data(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    async with async_session_factory() as db:
        actual_counts = await table_counts(db)
        assert actual_counts == manifest["counts"], {"expected": manifest["counts"], "actual": actual_counts}

        user = await db.get(User, uuid.UUID(manifest["user_id"]))
        policy = await db.get(Policy, uuid.UUID(manifest["policy_id"]))
        quarantine = await db.get(QuarantineFile, uuid.UUID(manifest["quarantine_id"]))
        event = await db.get(SecurityEvent, uuid.UUID(manifest["security_event_id"]))
        assert user is not None and user.username == USER_USERNAME and user.password_hash
        assert policy is not None and policy.name == POLICY_NAME
        assert str(policy.current_version_id) == manifest["policy_version_id"]
        assert quarantine is not None
        assert quarantine.original_name == ORIGINAL_NAME
        assert quarantine.status == QuarantineStatus.QUARANTINED
        assert quarantine.sha256 == manifest["sha256"]
        assert quarantine.storage_object_id == manifest["storage_path"]
        assert event is not None and event.event_type == SecurityEventType.FILE_QUARANTINED
        assert event.metadata_json == {"acceptance_marker": "v1-009", "sha256": manifest["sha256"]}

    restored = Path(manifest["storage_path"]).read_bytes()
    assert restored == PAYLOAD
    assert hashlib.sha256(restored).hexdigest() == manifest["sha256"]
    print("ACCEPT BR-06 all table counts and exact user/policy/audit/quarantine records match the baseline")
    print("ACCEPT BR-07 quarantine bytes match the backed-up content and SHA-256")


class ApiClient:
    def __init__(self) -> None:
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def request(self, method: str, path: str, payload: dict | None = None, expected: int = 200) -> dict:
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            f"{BASE}{path}", data=data, headers={"Content-Type": "application/json"}, method=method
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                body = response.read()
                assert response.status == expected
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            raise AssertionError(f"{method} {path}: {exc.code}: {exc.read().decode(errors='replace')}") from exc


def verify_functional() -> None:
    client = ApiClient()
    login = client.request("POST", "/auth/login", {"username": USER_USERNAME, "password": USER_PASSWORD})
    assert login["status"] == "ok"
    assert client.request("GET", "/auth/me")["username"] == USER_USERNAME
    print("ACCEPT BR-08 restored local user login succeeds")

    session = client.request("POST", "/sessions", expected=201)
    assert session["status"] == "ACTIVE"
    session_id = session["id"]
    terminated = client.request("POST", f"/sessions/{session_id}/terminate")
    assert terminated["status"] == "TERMINATED"
    print("ACCEPT BR-09 restored application starts and terminates a real browser session")

    health = client.request("GET", "/health")
    assert health["status"] == "ok"


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in {"seed", "corrupt", "verify-data", "verify-functional"}:
        raise SystemExit(f"usage: {sys.argv[0]} seed|corrupt|verify-data|verify-functional <manifest>")
    action, manifest = sys.argv[1], Path(sys.argv[2])
    if action == "seed":
        asyncio.run(seed(manifest))
    elif action == "corrupt":
        asyncio.run(corrupt(manifest))
    elif action == "verify-data":
        asyncio.run(verify_data(manifest))
    else:
        verify_functional()


if __name__ == "__main__":
    main()
