"""Tiny rate-limit adapter used until Redis-backed limits are added."""

from typing import Callable, TypeVar


F = TypeVar("F", bound=Callable)


class NoopLimiter:
    """Expose the same decorator shape as slowapi without adding runtime deps."""

    def limit(self, _rule: str) -> Callable[[F], F]:
        def decorator(func: F) -> F:
            return func

        return decorator


limiter = NoopLimiter()

LIMIT_UPLOAD = "10/minute"
LIMIT_SEARCH = "60/minute"
LIMIT_GRAPH_READ = "120/minute"
LIMIT_CHAT = "30/minute"
