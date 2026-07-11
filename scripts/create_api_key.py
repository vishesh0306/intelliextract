"""Issue a new API key (Phase 2 has no admin endpoint yet — that's Phase 9's
POST /api/v1/auth/keys). Only the hash is stored; the raw key is printed
once and cannot be recovered afterward.

Usage:
    uv run python -m scripts.create_api_key --owner "my-test-client" --rate-limit 30
"""

import argparse
import asyncio

from app.core.security import generate_api_key, hash_api_key
from app.db.session import async_session_factory
from app.models import ApiKey


async def main(owner: str, rate_limit: int) -> None:
    raw_key = generate_api_key()
    async with async_session_factory() as session:
        session.add(
            ApiKey(
                key_hash=hash_api_key(raw_key),
                owner_name=owner,
                rate_limit_per_min=rate_limit,
            )
        )
        await session.commit()

    print(f"API key for '{owner}' (limit: {rate_limit}/min):")
    print(raw_key)
    print("Store this now — it will not be shown again.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True)
    parser.add_argument("--rate-limit", type=int, default=30)
    args = parser.parse_args()
    asyncio.run(main(args.owner, args.rate_limit))
