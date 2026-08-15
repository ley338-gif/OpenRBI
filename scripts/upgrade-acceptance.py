"""Augment a 0.x fixture and verify it after upgrading to the v1 candidate."""

import asyncio
import hashlib
import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

import app.models  # noqa: F401 - register mapped tables
import pyotp
from app.core.crypto import decrypt_secret, encrypt_secret
from app.db.session import async_session_factory
from app.models.browser_node import BrowserNode
from app.models.browser_session import BrowserSession
from app.models.enums import QuarantineStatus, SecurityEventType
from app.models.ldap_config import LDAP_CONFIG_ID, LdapConfig
from app.models.policy import Policy
from app.models.quarantine import QuarantineFile
from app.models.security_event import SecurityEvent
from app.models.user import User
from app.models.worker_metric_sample import WorkerMetricSample
from app.services.security_events import record_security_event
from sqlalchemy import select

ADMIN_USERNAME = "acceptance_admin"
ADMIN_PASSWORD = "Acceptance-Admin-Password-2026!"
USER_USERNAME = "acceptance_user"
USER_PASSWORD = "Acceptance-User-Password-2026!"
POLICY_NAME = "backup-restore-acceptance-policy"
LDAP_BIND_PASSWORD = "upgrade-acceptance-bind-password"
PAYLOAD = b"OpenRBI v1 backup/restore quarantine evidence\n"
BASE = "http://localhost:8000"


async def augment(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    async with async_session_factory() as db:
        admin = await db.scalar(select(User).where(User.username == ADMIN_USERNAME))
        quarantine = await db.get(QuarantineFile, uuid.UUID(manifest["quarantine_id"]))
        node = await db.scalar(select(BrowserNode).where(BrowserNode.hostname == "upgrade-acceptance-node"))
        assert admin is not None and admin.mfa_enabled and admin.totp_secret_encrypted
        assert quarantine is not None and node is not None

        quarantine.status = QuarantineStatus.RELEASED
        quarantine.reviewed_at = datetime.now(UTC)
        quarantine.reviewed_by = admin.id
        quarantine.review_comment = "released before v1 upgrade"
        db.add(quarantine)
        release_event = await record_security_event(
            db,
            SecurityEventType.FILE_RELEASED,
            user_id=quarantine.user_id,
            session_id=quarantine.session_id,
            quarantine_file_id=quarantine.id,
            metadata={"acceptance_marker": "v1-010", "reviewed_by": str(admin.id)},
        )

        ldap = LdapConfig(
            id=LDAP_CONFIG_ID,
            enabled=False,
            server_uri="ldaps://directory.upgrade.invalid:636",
            use_starttls=False,
            bind_dn="CN=OpenRBI,OU=Services,DC=upgrade,DC=invalid",
            bind_password_encrypted=encrypt_secret(LDAP_BIND_PASSWORD),
            base_dn="DC=upgrade,DC=invalid",
            user_search_filter="(sAMAccountName={username})",
            group_attribute="memberOf",
            group_role_mapping={"CN=Admins,DC=upgrade,DC=invalid": "ADMIN"},
            updated_by=admin.id,
        )
        db.add(ldap)
        sample = WorkerMetricSample(
            node_id=node.id,
            recorded_at=datetime.now(UTC),
            cpu_percent=12.5,
            ram_used_mb=768,
            ram_total_mb=4096,
            active_sessions=0,
        )
        db.add(sample)
        await db.flush()
        manifest.update(
            {
                "admin_id": str(admin.id),
                "admin_totp_secret": decrypt_secret(admin.totp_secret_encrypted),
                "ldap_config_id": str(ldap.id),
                "release_event_id": str(release_event.id),
                "worker_id": str(node.id),
                "worker_hostname": node.hostname,
                "worker_sample_id": str(sample.id),
            }
        )
        await db.commit()
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    print("ACCEPT UP-01 0.x fixture includes users, MFA, LDAP, policy, sessions, audit, quarantine, and worker metadata")


async def verify_data(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    async with async_session_factory() as db:
        admin = await db.get(User, uuid.UUID(manifest["admin_id"]))
        user = await db.get(User, uuid.UUID(manifest["user_id"]))
        policy = await db.get(Policy, uuid.UUID(manifest["policy_id"]))
        session = await db.get(BrowserSession, uuid.UUID(manifest["session_id"]))
        quarantine = await db.get(QuarantineFile, uuid.UUID(manifest["quarantine_id"]))
        original_event = await db.get(SecurityEvent, uuid.UUID(manifest["security_event_id"]))
        release_event = await db.get(SecurityEvent, uuid.UUID(manifest["release_event_id"]))
        ldap = await db.get(LdapConfig, uuid.UUID(manifest["ldap_config_id"]))
        worker = await db.get(BrowserNode, uuid.UUID(manifest["worker_id"]))
        sample = await db.get(WorkerMetricSample, uuid.UUID(manifest["worker_sample_id"]))

        assert admin is not None and admin.username == ADMIN_USERNAME and admin.mfa_enabled
        assert admin.totp_secret_encrypted is not None
        assert decrypt_secret(admin.totp_secret_encrypted) == manifest["admin_totp_secret"]
        assert user is not None and user.username == USER_USERNAME and user.password_hash
        assert policy is not None and policy.name == POLICY_NAME
        assert str(policy.current_version_id) == manifest["policy_version_id"]
        assert session is not None and session.user_id == user.id
        assert quarantine is not None and quarantine.status == QuarantineStatus.RELEASED
        assert quarantine.sha256 == manifest["sha256"]
        assert original_event is not None and original_event.event_type == SecurityEventType.FILE_QUARANTINED
        assert release_event is not None and release_event.event_type == SecurityEventType.FILE_RELEASED
        assert ldap is not None and ldap.server_uri == "ldaps://directory.upgrade.invalid:636"
        assert ldap.group_role_mapping == {"CN=Admins,DC=upgrade,DC=invalid": "ADMIN"}
        assert ldap.bind_password_encrypted is not None
        assert decrypt_secret(ldap.bind_password_encrypted) == LDAP_BIND_PASSWORD
        assert worker is not None and worker.hostname == manifest["worker_hostname"]
        assert sample is not None and sample.node_id == worker.id

    content = Path(manifest["storage_path"]).read_bytes()
    assert content == PAYLOAD
    assert hashlib.sha256(content).hexdigest() == manifest["sha256"]
    print("ACCEPT UP-05 exact pre-upgrade identities, MFA/LDAP secrets, policy, session, audit, quarantine, and worker rows survived")


class ApiClient:
    def __init__(self) -> None:
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def _csrf_token(self) -> str | None:
        for cookie in self.cookies:
            if cookie.name == "csrf_token":
                return cookie.value
        return None

    def raw(self, method: str, path: str, payload: dict | None = None, expected: int = 200) -> bytes:
        # RBI-POST-003: mutating requests need a matching X-CSRF-Token
        # header (app/core/csrf.py) — bootstrap the cookie with a cheap GET
        # first if this client doesn't have one yet, same as the real
        # frontend's shared ApiClient (frontend/shared/api/client.ts).
        if method != "GET" and self._csrf_token() is None:
            self.raw("GET", "/health")
        data = None if payload is None else json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if method != "GET":
            token = self._csrf_token()
            if token:
                headers["X-CSRF-Token"] = token
        request = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=30) as response:
                assert response.status == expected
                return response.read()
        except urllib.error.HTTPError as exc:
            raise AssertionError(f"{method} {path}: {exc.code}: {exc.read().decode(errors='replace')}") from exc

    def request(self, method: str, path: str, payload: dict | None = None, expected: int = 200) -> dict:
        body = self.raw(method, path, payload, expected)
        return json.loads(body) if body else {}


def verify_functional(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    admin_client = ApiClient()
    login = admin_client.request(
        "POST", "/auth/login", {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
    )
    assert login["status"] == "mfa_required"
    verified = admin_client.request(
        "POST",
        "/auth/mfa/verify",
        {"mfa_token": login["mfa_token"], "code": pyotp.TOTP(manifest["admin_totp_secret"]).now()},
    )
    assert verified["status"] == "ok"
    assert admin_client.request("GET", "/auth/me")["username"] == ADMIN_USERNAME
    deadline = time.monotonic() + 180
    while True:
        health = admin_client.request("GET", "/admin/health")
        if health["status"] == "HEALTHY":
            break
        if time.monotonic() >= deadline:
            raise AssertionError(health)
        time.sleep(5)
    print("ACCEPT UP-06 restored ADMIN password + MFA login and aggregate health succeed")

    user_client = ApiClient()
    login = user_client.request(
        "POST", "/auth/login", {"username": USER_USERNAME, "password": USER_PASSWORD}
    )
    assert login["status"] == "ok"
    token = user_client.request("POST", f"/files/{manifest['quarantine_id']}/download-token")["token"]
    downloaded = user_client.raw("GET", f"/files/download/{urllib.parse.quote(token)}")
    assert downloaded == PAYLOAD
    print("ACCEPT UP-07 restored USER login and single-use quarantine download succeed")

    session = user_client.request("POST", "/sessions", expected=201)
    assert session["status"] == "ACTIVE"
    terminated = user_client.request("POST", f"/sessions/{session['id']}/terminate")
    assert terminated["status"] == "TERMINATED"
    print("ACCEPT UP-08 current v1 image starts and terminates a real browser session with upgraded state")


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in {"augment", "verify-data", "verify-functional"}:
        raise SystemExit(f"usage: {sys.argv[0]} augment|verify-data|verify-functional <manifest>")
    action, manifest = sys.argv[1], Path(sys.argv[2])
    if action == "augment":
        asyncio.run(augment(manifest))
    elif action == "verify-data":
        asyncio.run(verify_data(manifest))
    else:
        verify_functional(manifest)


if __name__ == "__main__":
    main()
