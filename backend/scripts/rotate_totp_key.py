"""Roadmap Phase A / A6 — re-encrypts every stored TOTP secret from an old
OPENRBI_TOTP_SECRET_ENCRYPTION_KEY to a new one.

Rotating this key is NOT as simple as editing .env and restarting: every
enrolled user's TOTP secret is stored Fernet-encrypted (users.totp_secret_
encrypted, see app/core/crypto.py) under the *current* key. Swapping the key
without this step would make every existing secret permanently
undecryptable — every enrolled admin/security-reviewer/user would be locked
out of MFA on their next login, with no self-service recovery (their
recovery codes are hashed, single-use, and unrelated to this key).

Run via scripts/rotate-secrets.sh, which copies this into the backend
container and passes both keys as arguments — never via environment
variables the process's own Settings might also read, to avoid any
ambiguity about which key is "the configured one" while this runs.

Deliberately reimplements Fernet-key derivation inline rather than importing
app.core.crypto's module-level _fernet(), which always reads from the
global Settings singleton (a single, currently-configured key) — this
script needs two independent instances (old and new) at once.
"""

import argparse
import asyncio
import base64
import sys

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.user import User


def _fernet_from_hex(hex_key: str) -> Fernet:
    raw = bytes.fromhex(hex_key)
    if len(raw) != 32:
        raise ValueError("key must decode to exactly 32 bytes (openssl rand -hex 32)")
    return Fernet(base64.urlsafe_b64encode(raw))


async def rotate(old_key: str, new_key: str, dry_run: bool) -> None:
    old_fernet = _fernet_from_hex(old_key)
    new_fernet = _fernet_from_hex(new_key)

    async with async_session_factory() as db:
        result = await db.execute(select(User).where(User.totp_secret_encrypted.is_not(None)))
        users = result.scalars().all()

        print(f"Found {len(users)} user(s) with an encrypted TOTP secret.")
        failures = []
        for user in users:
            try:
                plaintext = old_fernet.decrypt(user.totp_secret_encrypted).decode("utf-8")
            except InvalidToken:
                # Already rotated (a re-run after a partial failure), or
                # encrypted under a key that isn't the one supplied as
                # --old-key. Either way, do not touch it silently.
                try:
                    new_fernet.decrypt(user.totp_secret_encrypted)
                    print(f"  {user.username}: already encrypted under --new-key, skipping")
                    continue
                except InvalidToken:
                    failures.append(user.username)
                    print(f"  {user.username}: FAILED to decrypt under either key — left untouched")
                    continue
            if not dry_run:
                user.totp_secret_encrypted = new_fernet.encrypt(plaintext.encode("utf-8"))
            print(f"  {user.username}: re-encrypted{' (dry run, not saved)' if dry_run else ''}")

        if failures:
            print(f"\n{len(failures)} user(s) could not be decrypted under --old-key: {', '.join(failures)}")
            print("Nothing was committed. Fix --old-key and re-run before proceeding.")
            sys.exit(1)

        if dry_run:
            print("\nDry run only — no changes committed. Re-run without --dry-run to apply.")
            await db.rollback()
        else:
            await db.commit()
            print(f"\nCommitted: {len(users)} secret(s) re-encrypted under the new key.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-key", required=True, help="current OPENRBI_TOTP_SECRET_ENCRYPTION_KEY (hex)")
    parser.add_argument("--new-key", required=True, help="new key to rotate to (hex, e.g. from openssl rand -hex 32)")
    parser.add_argument("--dry-run", action="store_true", help="decrypt/re-encrypt in memory but do not commit")
    args = parser.parse_args()
    asyncio.run(rotate(args.old_key, args.new_key, args.dry_run))
