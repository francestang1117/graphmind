"""Optional Sentry setup for production error tracking."""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings

log = logging.getLogger(__name__)

try:
    import sentry_sdk
except ImportError:  # pragma: no cover - depends on optional production package
    sentry_sdk = None  # type: ignore[assignment]


def configure_sentry() -> None:
    """Initialize Sentry when a DSN is configured."""
    if not settings.SENTRY_ENABLED or not settings.SENTRY_DSN:
        return

    if sentry_sdk is None:
        log.warning("sentry-sdk is not installed; Sentry reporting is disabled")
        return

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        release=sentry_release(),
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        send_default_pii=False,
    )
    log.info("Sentry error tracking enabled for %s", settings.ENVIRONMENT)


def sentry_release() -> str:
    """Build a release name that can point back to a deployed commit."""
    base = f"{settings.PROJECT_NAME}@{settings.VERSION}"
    sha = settings.GIT_SHA.strip()
    if not sha:
        return base
    # Twelve chars is enough to identify the commit without making Sentry's
    # release name noisy.
    return f"{base}+{sha[:12]}"


def capture_exception(exc: BaseException, **context: Any) -> None:
    """Send an exception to Sentry if reporting is active."""
    if sentry_sdk is None or not settings.SENTRY_ENABLED or not settings.SENTRY_DSN:
        return

    try:
        with sentry_sdk.new_scope() as scope:
            for key, value in context.items():
                if value is not None:
                    scope.set_extra(key, value)
            sentry_sdk.capture_exception(exc)
    except Exception as report_error:  # pragma: no cover - do not let reporting break API errors
        # Sentry is helpful, but it should never become the new outage.
        log.warning("Could not report exception to Sentry: %s", report_error)
