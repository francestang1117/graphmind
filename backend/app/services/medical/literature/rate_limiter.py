"""Cross-process pacing for PubMed E-utilities requests."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
import time
from typing import Any

from app.core.config import LOCAL_ENVIRONMENTS, settings

log = logging.getLogger(__name__)


_TOKEN_BUCKET_SCRIPT = """
local now = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local capacity = tonumber(ARGV[3])
local state = redis.call('HMGET', KEYS[1], 'tokens', 'updated_at')
local tokens = tonumber(state[1])
local updated_at = tonumber(state[2])
if not tokens then tokens = capacity end
if not updated_at then updated_at = now end
tokens = math.min(capacity, tokens + math.max(0, now - updated_at) * rate)
if tokens >= 1 then
  tokens = tokens - 1
  redis.call('HSET', KEYS[1], 'tokens', tokens, 'updated_at', now)
  redis.call('EXPIRE', KEYS[1], math.ceil(capacity / rate) + 2)
  return {1, 0}
end
local wait_for = (1 - tokens) / rate
redis.call('HSET', KEYS[1], 'tokens', tokens, 'updated_at', now)
redis.call('EXPIRE', KEYS[1], math.ceil(capacity / rate) + 2)
return {0, wait_for}
"""


class PubMedRateLimitUnavailable(RuntimeError):
    """Raised when a production process cannot coordinate its request budget."""


class PubMedRateLimiter:
    """Use one Redis token bucket for every API process and worker.

    Development and test environments may fall back to a process-local clock.
    Production and staging fail closed when Redis cannot coordinate the shared
    budget, because a per-instance limiter would not protect NCBI.
    """

    def __init__(
        self,
        *,
        redis_url: str | None = None,
        redis_client: Any | None = None,
        no_key_requests_per_second: int | None = None,
        with_key_requests_per_second: int | None = None,
        requests_per_second: int | None = None,
        strict: bool | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        wall_clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if requests_per_second is not None:
            no_key_requests_per_second = requests_per_second
            with_key_requests_per_second = requests_per_second
        self.redis_url = redis_url or settings.REDIS_URL
        self.redis_client = redis_client
        self.no_key_rate = max(
            1,
            int(
                no_key_requests_per_second
                if no_key_requests_per_second is not None
                else settings.PUBMED_RATE_LIMIT_NO_KEY_REQUESTS_PER_SECOND
            ),
        )
        self.with_key_rate = max(
            1,
            int(
                with_key_requests_per_second
                if with_key_requests_per_second is not None
                else settings.PUBMED_RATE_LIMIT_WITH_KEY_REQUESTS_PER_SECOND
            ),
        )
        environment = settings.ENVIRONMENT.strip().lower()
        self.strict = (
            bool(settings.PUBMED_RATE_LIMIT_REDIS_REQUIRED)
            and environment not in LOCAL_ENVIRONMENTS
            if strict is None
            else bool(strict)
        )
        self.sleep = sleep
        self.wall_clock = wall_clock
        self.monotonic_clock = monotonic_clock
        self.redis_key = "graphmind:pubmed:rate:v1"
        self._redis_unavailable = False
        self._warned_fallback = False
        self._local_lock = asyncio.Lock()
        self._last_local_request_at = 0.0

    async def acquire(self, *, has_api_key: bool = False) -> None:
        """Wait for one globally coordinated PubMed request slot."""
        if not settings.PUBMED_RATE_LIMIT_ENABLED:
            return

        rate = self.with_key_rate if has_api_key else self.no_key_rate
        redis_client = await self._get_redis_client()
        if redis_client is not None:
            try:
                while True:
                    result = await redis_client.eval(
                        _TOKEN_BUCKET_SCRIPT,
                        1,
                        self.redis_key,
                        str(self.wall_clock()),
                        str(rate),
                        str(rate),
                    )
                    granted, wait_for = _bucket_result(result)
                    if granted:
                        return
                    await self.sleep(min(max(wait_for, 0.01), 10.0))
            except Exception as exc:
                self.redis_client = None
                self._redis_unavailable = True
                if self.strict:
                    raise PubMedRateLimitUnavailable from exc

        if self.strict:
            raise PubMedRateLimitUnavailable
        if not self._warned_fallback:
            log.warning("PubMed Redis rate limiter unavailable; using local pacing")
            self._warned_fallback = True
        await self._acquire_local(rate)

    async def _get_redis_client(self) -> Any | None:
        if self.redis_client is not None:
            return self.redis_client
        if self._redis_unavailable:
            return None
        try:
            import redis.asyncio as aioredis

            self.redis_client = aioredis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
            )
        except Exception:
            self._redis_unavailable = True
            return None
        return self.redis_client

    async def _acquire_local(self, rate: int) -> None:
        interval = 1.0 / max(1, rate)
        async with self._local_lock:
            now = self.monotonic_clock()
            wait_for = interval - (now - self._last_local_request_at)
            if wait_for > 0:
                await self.sleep(wait_for)
            self._last_local_request_at = self.monotonic_clock()


def _bucket_result(result: Any) -> tuple[bool, float]:
    if isinstance(result, (list, tuple)) and len(result) >= 2:
        try:
            return bool(int(result[0])), max(0.0, float(result[1]))
        except (TypeError, ValueError):
            return False, 1.0
    return bool(result), 0.0


_default_limiter: PubMedRateLimiter | None = None


def get_pubmed_rate_limiter() -> PubMedRateLimiter:
    """Return the process singleton used when a provider has no test override."""
    global _default_limiter
    if _default_limiter is None:
        _default_limiter = PubMedRateLimiter()
    return _default_limiter
