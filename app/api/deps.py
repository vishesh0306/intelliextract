from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis_client
from app.core.security import hash_api_key
from app.db.session import get_db
from app.models import ApiKey
from app.services.rate_limiter import TokenBucketRateLimiter


async def get_current_api_key(
    db: Annotated[AsyncSession, Depends(get_db)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> ApiKey:
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-API-Key header"
        )

    api_key = await db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(x_api_key)))
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    return api_key


async def enforce_rate_limit(
    api_key: Annotated[ApiKey, Depends(get_current_api_key)],
    redis_client: Annotated[Redis, Depends(get_redis_client)],
) -> ApiKey:
    limiter = TokenBucketRateLimiter(redis_client)
    allowed, retry_after = await limiter.check(
        key=f"ratelimit:{api_key.id}",
        capacity=api_key.rate_limit_per_min,
        refill_rate=api_key.rate_limit_per_min / 60,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )

    return api_key
