from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.redis import get_redis_client
from app.core.security import generate_api_key, hash_api_key
from app.db.session import async_session_factory
from app.main import app
from app.models import ApiKey


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def api_key_factory() -> AsyncIterator[Callable[..., Awaitable[tuple[str, ApiKey]]]]:
    """Creates real ApiKey rows against the dev Postgres/Redis and cleans
    them up afterward, so tests exercise the actual auth + rate-limit path
    instead of mocking the DB/Redis layer.
    """
    created_ids = []

    async def _create(rate_limit_per_min: int = 30) -> tuple[str, ApiKey]:
        raw_key = generate_api_key()
        async with async_session_factory() as session:
            api_key = ApiKey(
                key_hash=hash_api_key(raw_key),
                owner_name="test-client",
                rate_limit_per_min=rate_limit_per_min,
            )
            session.add(api_key)
            await session.commit()
            await session.refresh(api_key)

        created_ids.append(api_key.id)
        await get_redis_client().delete(f"ratelimit:{api_key.id}")
        return raw_key, api_key

    yield _create

    async with async_session_factory() as session:
        for key_id in created_ids:
            await session.execute(delete(ApiKey).where(ApiKey.id == key_id))
        await session.commit()

    redis_client = get_redis_client()
    for key_id in created_ids:
        await redis_client.delete(f"ratelimit:{key_id}")
