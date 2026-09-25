"""Seeds the standard policy templates (app/services/standard_policies.py,
where the definitions and the once-per-installation bookkeeping live).

Normally never run by hand: first-run setup seeds them, and
scripts/deploy.sh runs this on every install/update to add templates
introduced by a newer release. Safe to re-run at any time.

Run inside the backend container (see scripts/seed-standard-policies.sh):
    docker exec openrbi-backend-1 python /app/seed_standard_policies.py
"""

import asyncio
import json

from app.db.session import async_session_factory
from app.models.system_state import SYSTEM_STATE_ID, SystemState
from app.services.standard_policies import seed_standard_policies


async def main() -> None:
    async with async_session_factory() as db:
        state = await db.get(SystemState, SYSTEM_STATE_ID)
        if state is None or not state.initialized:
            # Not an error: on a fresh install first-run setup seeds them.
            print(json.dumps({"skipped": "first-run setup not completed yet; setup seeds the templates"}))
            return
        created, skipped = await seed_standard_policies(db)
        await db.commit()
        print(json.dumps({"created": created, "skipped_already_exists": skipped}))


if __name__ == "__main__":
    asyncio.run(main())
