from functools import lru_cache

from redis import Redis
from rq import Queue

from app.core.config import get_settings

# RQ requires a *sync* redis-py client (it's not async-aware), separate from
# the redis.asyncio client the API/rate-limiter use.


@lru_cache
def get_task_queue() -> Queue:
    redis_conn = Redis.from_url(get_settings().redis_url)
    return Queue("default", connection=redis_conn)
