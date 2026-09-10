"""Tests for the shared PubMed request budget."""

import asyncio

import pytest

from app.services.medical.literature.rate_limiter import (
    PubMedRateLimitUnavailable,
    PubMedRateLimiter,
    get_pubmed_rate_limiter,
)


class _GrantingRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def eval(self, *args: object) -> list[int]:
        self.calls.append(args)
        return [1, 0]


class _BrokenRedis:
    async def eval(self, *args: object) -> list[int]:
        raise OSError("redis unavailable")


def test_rate_limiter_uses_redis_token_bucket() -> None:
    redis = _GrantingRedis()
    limiter = PubMedRateLimiter(
        redis_client=redis,
        no_key_requests_per_second=3,
        with_key_requests_per_second=10,
        strict=True,
    )

    asyncio.run(limiter.acquire(has_api_key=True))

    assert len(redis.calls) == 1
    assert redis.calls[0][1] == 1
    assert redis.calls[0][-2:] == ("10", "10")


def test_rate_limiter_fails_closed_when_redis_is_unavailable() -> None:
    limiter = PubMedRateLimiter(
        redis_client=_BrokenRedis(),
        requests_per_second=3,
        strict=True,
    )

    with pytest.raises(PubMedRateLimitUnavailable):
        asyncio.run(limiter.acquire())


def test_default_limiter_factory_does_not_share_an_async_client() -> None:
    assert get_pubmed_rate_limiter() is not get_pubmed_rate_limiter()


def test_local_fallback_can_be_used_across_event_loops() -> None:
    limiter = PubMedRateLimiter(
        redis_client=_BrokenRedis(),
        requests_per_second=100,
        strict=False,
    )

    asyncio.run(limiter.acquire())
    asyncio.run(limiter.acquire())
