"""Turn AI features on or off for one organisation (operator tool, not part of the app).

    uv run python -m sia.scripts.ai_access --list
    uv run python -m sia.scripts.ai_access --org <organization-id> --on
    uv run python -m sia.scripts.ai_access --org <organization-id> --off

On the server:  docker compose -f deploy/compose.prod.yaml run --rm --no-deps api \
                    python -m sia.scripts.ai_access --list

Connects as the schema owner (an operator action across organisations), never as the app role.
"""

import argparse
import asyncio
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from sia.core.config import get_settings


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--org", type=uuid.UUID)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--on", action="store_true")
    group.add_argument("--off", action="store_true")
    group.add_argument("--list", action="store_true")
    args = parser.parse_args()

    engine = create_async_engine(get_settings().migration_database_url)
    try:
        async with engine.begin() as conn:
            if args.list:
                rows = await conn.execute(
                    text("SELECT id, name, ai_enabled FROM organizations ORDER BY created_at")
                )
                for org_id, name, enabled in rows:
                    print(f"{org_id}  {'AI on ' if enabled else 'AI off'}  {name}")
                return
            if args.org is None:
                parser.error("--org is required with --on/--off")
            result = await conn.execute(
                text("UPDATE organizations SET ai_enabled = :on WHERE id = :id RETURNING name"),
                {"on": args.on, "id": args.org},
            )
            name = result.scalar_one_or_none()
            if name is None:
                parser.error(f"No organisation {args.org}")
            print(f"AI {'enabled' if args.on else 'disabled'} for {name!r}.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
