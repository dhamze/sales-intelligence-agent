"""Seed realistic-looking synthetic companies into a user's active organisation (development only).

    # 1. Sign up through the API (or the UI) first, then:
    uv run python -m sia.scripts.seed_companies --email you@example.com --count 50000

Data is generated deterministically (same --seed -> same data) and inserted through the
restricted runtime role with tenant context set, exactly like the application does.
"""

import argparse
import asyncio
import random
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert, select

from sia.core.config import get_settings
from sia.core.db import create_engine, create_sessionmaker
from sia.core.tenancy import set_tenant_context
from sia.modules.companies.models import Company, RecordSource
from sia.modules.identity import repository as identity_repository
from sia.modules.identity.models import User

_PREFIXES = [
    "Acme", "Apex", "Blue", "Bright", "Cedar", "Clear", "Core", "Delta", "Echo", "Ever",
    "First", "Global", "Green", "Harbor", "Iron", "Lumen", "Maple", "Nova", "North", "Oak",
    "Peak", "Pine", "Prime", "Quantum", "Red", "River", "Silver", "Sky", "Solar", "Summit",
    "Swift", "True", "Union", "Vertex", "Vista", "West", "Zen", "Atlas", "Beacon", "Crest",
]  # fmt: skip
_SUFFIXES = [
    "Analytics", "Bank", "Bio", "Cloud", "Logistics", "Dynamics", "Energy", "Foods", "Health",
    "Holdings", "Insights", "Labs", "Media", "Networks", "Partners", "Robotics", "Security",
    "Software", "Systems", "Technologies", "Ventures", "Works", "Retail", "Capital", "Motors",
]  # fmt: skip
_INDUSTRIES = [
    "Software", "Fintech", "Healthcare", "Manufacturing", "Retail", "Logistics", "Energy",
    "Media", "Education", "Cybersecurity", "Biotech", "Real Estate", "Consulting",
]  # fmt: skip
_COUNTRIES = ["US", "GB", "DE", "FR", "NL", "SE", "CA", "AU", "IE", "ES", "IN", "SG", "JP"]
_TLDS = ["com", "io", "co", "ai", "net", "co.uk", "de"]

BATCH = 2000


def _company_rows(
    rng: random.Random, organization_id: uuid.UUID, count: int
) -> list[dict[str, object]]:
    now = datetime.now(UTC)
    rows = []
    for i in range(count):
        name = f"{rng.choice(_PREFIXES)} {rng.choice(_SUFFIXES)}"
        slug = name.lower().replace(" ", "")
        rows.append(
            {
                "id": uuid.uuid4(),
                "organization_id": organization_id,
                "name": name if i % 7 else f"{name} {i}",  # plenty of duplicate names, like reality
                "domain": f"{slug}{i}.{rng.choice(_TLDS)}",
                "industry": rng.choice(_INDUSTRIES),
                "employee_count": int(rng.lognormvariate(4, 1.6)),
                "country": rng.choice(_COUNTRIES),
                "source": RecordSource.IMPORT if i % 3 else RecordSource.MANUAL,
                "attributes": {},
                "created_at": now - timedelta(minutes=rng.randint(0, 2 * 365 * 24 * 60)),
            }
        )
    return rows


async def seed(email: str, count: int, seed_value: int) -> None:
    settings = get_settings()
    if settings.is_production:
        raise SystemExit("Refusing to seed a production database.")
    engine = create_engine(settings)
    sessionmaker = create_sessionmaker(engine)
    rng = random.Random(seed_value)  # noqa: S311 -- synthetic data, not security-relevant
    try:
        async with sessionmaker() as db:
            user = (await db.scalars(select(User).where(User.email == email.lower()))).one_or_none()
            if user is None:
                raise SystemExit(f"No user {email!r}. Sign up through the API first.")
            await set_tenant_context(db, user_id=user.id, organization_id=None)
            organization_id = await identity_repository.default_organization_for(db, user.id)
            if organization_id is None:
                raise SystemExit("That user belongs to no organization.")

            started = time.perf_counter()
            rows = _company_rows(rng, organization_id, count)
            for start in range(0, count, BATCH):
                await set_tenant_context(db, user_id=user.id, organization_id=organization_id)
                await db.execute(insert(Company), rows[start : start + BATCH])
                await db.commit()
            elapsed = time.perf_counter() - started
            print(f"Inserted {count} companies into {organization_id} in {elapsed:.1f}s")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True, help="An existing user; seeds their org")
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42, help="Random seed (reproducible data)")
    args = parser.parse_args()
    asyncio.run(seed(args.email, args.count, args.seed))


if __name__ == "__main__":
    main()
