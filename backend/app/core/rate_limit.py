"""Small wrapper around slowapi so routes can share the same limits."""

from __future__ import annotations

import logging
from typing import Callable, TypeVar

from fastapi import FastAPI, Request

from app.core.config import settings

log = logging.getLogger(__name__)
F = TypeVar("F", bound=Callable)


class NoopLimiter:
    """Used when local setup does not have Redis/slowapi ready."""

    enabled = False

    def limit(self, _rule: str) -> Callable[[F], F]:
        def decorator(func: F) -> F:
            return func

        return decorator


def get_client_ip(request: Request) -> str:
    """Return the client IP, respecting X-Forwarded-For from trusted proxies."""
    client_host = request.client.host if request.client else "unknown"
    trusted = set(settings.TRUSTED_PROXY_IPS)

    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for and client_host in trusted:
        # Only trust this header when the immediate peer is our proxy. If the
        # app is exposed directly, clients can spoof X-Forwarded-For themselves.
        return forwarded_for.split(",")[0].strip()

    return client_host


def build_limiter():
    """Build the limiter used by FastAPI."""
    if not settings.RATE_LIMIT_ENABLED:
        return NoopLimiter()

    try:
        from slowapi import Limiter
    except ImportError:
        log.warning("slowapi is not installed; rate limiting disabled")
        return NoopLimiter()

    storage_uri = settings.RATE_LIMIT_STORAGE_URI or settings.REDIS_URL
    if storage_uri.startswith("redis") and not _redis_is_available(storage_uri):
        # Don't make normal local runs depend on Redis.
        log.warning("Redis is not reachable for rate limiting; rate limiting disabled")
        return NoopLimiter()

    limiter = Limiter(
        key_func=get_client_ip,
        default_limits=[settings.RATE_LIMIT_DEFAULT],
        storage_uri=storage_uri,
        strategy="fixed-window",
        headers_enabled=True,
    )
    limiter.enabled = True
    return limiter


def _redis_is_available(redis_url: str) -> bool:
    """Check Redis once at startup so every request does not pay a timeout."""
    try:
        import redis

        client = redis.Redis.from_url(
            redis_url,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
        )
        client.ping()
        client.close()
        return True
    except Exception:
        return False


def configure_rate_limiting(app: FastAPI) -> None:
    """Wire slowapi into FastAPI when the real limiter is active."""
    app.state.limiter = limiter
    if not getattr(limiter, "enabled", False):
        return

    try:
        from slowapi import _rate_limit_exceeded_handler
        from slowapi.errors import RateLimitExceeded
        from slowapi.middleware import SlowAPIMiddleware
    except ImportError:
        log.warning("slowapi middleware is unavailable; rate limiting disabled")
        return

    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)


limiter = build_limiter()

# Endpoint-specific rules. Keeping these named makes route decorators read like
# intent: uploads are protected because they hit disk, chat because it will hit
# paid AI calls, and graph/search because they rebuild in-memory indexes today.
upload_limit = limiter.limit(settings.RATE_LIMIT_UPLOAD)
chat_limit = limiter.limit(settings.RATE_LIMIT_CHAT)
search_limit = limiter.limit(settings.RATE_LIMIT_SEARCH)
graph_read_limit = limiter.limit(settings.RATE_LIMIT_GRAPH_READ)
video_limit = limiter.limit(settings.RATE_LIMIT_VIDEO)

# Backward-compatible constants for older imports/tests.
LIMIT_UPLOAD = settings.RATE_LIMIT_UPLOAD
LIMIT_SEARCH = settings.RATE_LIMIT_SEARCH
LIMIT_GRAPH_READ = settings.RATE_LIMIT_GRAPH_READ
LIMIT_CHAT = settings.RATE_LIMIT_CHAT
