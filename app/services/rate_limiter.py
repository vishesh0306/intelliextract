import time

from redis.asyncio import Redis

# Token bucket, evaluated atomically in Redis via EVAL so that concurrent
# requests against the same key can't race between reading the current
# token count and writing the decremented one (a plain GET-then-SET from
# Python would let two concurrent requests both read N tokens and both
# spend one, over-admitting by one request every time they overlap).
#
# KEYS[1] = bucket key (e.g. "ratelimit:<api_key_id>")
# ARGV[1] = capacity (max tokens / burst size)
# ARGV[2] = refill_rate (tokens added per second)
# ARGV[3] = now (unix timestamp, seconds, float)
_TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local bucket = redis.call("HMGET", key, "tokens", "last_refill")
local tokens = tonumber(bucket[1])
local last_refill = tonumber(bucket[2])

if tokens == nil then
    tokens = capacity
    last_refill = now
end

local elapsed = math.max(0, now - last_refill)
tokens = math.min(capacity, tokens + elapsed * refill_rate)

local allowed = 0
if tokens >= 1 then
    tokens = tokens - 1
    allowed = 1
end

redis.call("HMSET", key, "tokens", tostring(tokens), "last_refill", tostring(now))
redis.call("EXPIRE", key, 120)

return {allowed, tostring(tokens)}
"""


class TokenBucketRateLimiter:
    def __init__(self, redis_client: Redis) -> None:
        self._script = redis_client.register_script(_TOKEN_BUCKET_SCRIPT)

    async def check(self, key: str, capacity: int, refill_rate: float) -> tuple[bool, float]:
        """Try to spend one token from `key`'s bucket.

        Returns (allowed, retry_after_seconds). retry_after_seconds is 0
        when allowed, otherwise the time until at least one token is
        available again.
        """
        now = time.time()
        allowed_raw, tokens_raw = await self._script(keys=[key], args=[capacity, refill_rate, now])
        allowed = bool(int(allowed_raw))
        if allowed:
            return True, 0.0

        tokens = float(tokens_raw)
        retry_after = (1 - tokens) / refill_rate if refill_rate > 0 else 1.0
        return False, max(retry_after, 0.0)
