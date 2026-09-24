"""Break-glass reset of a LOCAL account's password from the Docker host,
for when no working admin session exists to do it through the Admin Portal
(Users -> user -> Reset password). Typical case: the one local ADMIN kept
for break-glass access (docs/admin-guide.md) has lost its password, its
TOTP device is fine, and the operator has SSH access to the host only.

Uses the exact same app.services.users.reset_password() the Admin API
calls — correct Argon2 hashing and a PASSWORD_RESET_BY_ADMIN security
event — never a hand-rolled UPDATE. Also clears the account's brute-force
login lockout (recording ACCOUNT_UNLOCKED if it was actually locked), since
an operator resetting a forgotten password has usually tripped it by then.

Does NOT touch MFA: an enrolled TOTP device stays enrolled and is still
required at the next login. A lost TOTP device is a different recovery
path (recovery codes, or another admin's Reset MFA).

Refuses LDAP-provisioned accounts (no local password — the directory owns
it) and unknown usernames. The new password is read from the terminal (or
one line of stdin when not a TTY), never from argv, so it doesn't end up in
shell history or the host's process list.

Run via scripts/reset-local-password.sh, which copies this into the backend
container — same pattern as scripts/rotate-totp-key.sh.
"""

import argparse
import asyncio
import getpass
import sys
import uuid

from sqlalchemy import select

from app.core.sessions import clear_login_failures, get_login_lockout_status
from app.db.session import async_session_factory
from app.models.role import Role
from app.models.user import User
from app.services.users import reset_password, set_active, unlock_account

# Actor recorded in the security events this writes — metadata only (a
# string in the event's JSON blob, never a foreign key), same sentinel
# approach as setup_service.BOOTSTRAP_SYSTEM_ACTOR_ID. Lets a reviewer tell
# a host-side break-glass reset apart from one done by a real admin.
BREAK_GLASS_CLI_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-00000b7ea4c1")


def _read_new_password() -> str:
    if sys.stdin.isatty():
        first = getpass.getpass("New password: ")
        second = getpass.getpass("Repeat new password: ")
        if first != second:
            print("refusing: the two passwords don't match.", file=sys.stderr)
            sys.exit(1)
        password = first
    else:
        password = sys.stdin.readline().rstrip("\r\n")
    if not password:
        print("refusing: empty password.", file=sys.stderr)
        sys.exit(1)
    return password


async def main(username: str, *, enable: bool) -> None:
    async with async_session_factory() as db:
        row = (
            await db.execute(select(User, Role.name).join(Role, Role.id == User.role_id).where(User.username == username))
        ).first()
        if row is None:
            print(f"refusing: no account named '{username}'.", file=sys.stderr)
            sys.exit(1)
        user, role_name = row
        if user.password_hash is None:
            print(
                f"refusing: '{username}' is LDAP-provisioned — its password is owned by the directory, not OpenRBI.",
                file=sys.stderr,
            )
            sys.exit(1)

        password = _read_new_password()

        await reset_password(db, user, new_password=password, actor_id=BREAK_GLASS_CLI_ACTOR_ID)
        lockout = await get_login_lockout_status(username)
        if lockout.get("locked"):
            await unlock_account(db, user, actor_id=BREAK_GLASS_CLI_ACTOR_ID)
        elif lockout.get("failure_count"):
            # Not locked yet, but a partial failure count would still lock
            # the account again after only a few more typos.
            await clear_login_failures(username)
        if enable and not user.is_active:
            await set_active(db, user, active=True, actor_id=BREAK_GLASS_CLI_ACTOR_ID)
        await db.commit()

        print(f"password reset for {role_name} '{username}' ({user.id}).")
        if lockout.get("locked"):
            print("  login lockout cleared.")
        if not user.is_active:
            print("  WARNING: this account is DISABLED and still cannot log in — re-run with --enable.")
        elif enable:
            print("  account is enabled.")
        if user.mfa_enabled:
            print("  MFA is unchanged — the enrolled TOTP device is still required at login.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Break-glass reset of a LOCAL account's password.")
    parser.add_argument("username")
    parser.add_argument("--enable", action="store_true", help="also re-enable the account if it is disabled")
    args = parser.parse_args()
    asyncio.run(main(args.username, enable=args.enable))
