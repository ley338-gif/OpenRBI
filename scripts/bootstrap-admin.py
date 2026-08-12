"""One-time bootstrap for the very first ADMIN account.

There is no seeded admin user (only the USER/SECURITY_REVIEWER/ADMIN
*roles* are seeded by migration) and no self-registration — every other
admin account is created via POST /admin/users, which itself requires an
already-authenticated admin. This script breaks that chicken-and-egg
problem exactly once, using the same create_user() service function the
admin API calls (correct password hashing, USER_CREATED security event),
never a hand-rolled INSERT.

Usage (run inside the backend container):
    docker exec -it openrbi-backend-1 python /app/bootstrap_admin.py <username> <password>

Refuses to run if any ADMIN already exists, so it can't be used to slip
in a second admin outside the normal, audited admin API.
"""

import asyncio
import sys
import uuid

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.role import Role
from app.models.user import User
from app.services.users import create_user


async def main(username: str, password: str) -> None:
    async with async_session_factory() as db:
        existing_admin = await db.execute(
            select(User).join(Role).where(Role.name == "ADMIN")
        )
        if existing_admin.scalars().first() is not None:
            print("refusing: an ADMIN account already exists — use the Admin Portal/API instead.")
            sys.exit(1)

        user = await create_user(
            db, username=username, password=password, role_name="ADMIN",
            group_ids=[], created_by=uuid.uuid4(),
        )
        await db.commit()
        print(f"created ADMIN '{user.username}' ({user.id}) — MFA enrollment is mandatory on first login.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: bootstrap_admin.py <username> <password>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
