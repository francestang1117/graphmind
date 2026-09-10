"""Runtime configuration refuses unsafe non-local settings."""

import pytest

from app.core.config import (
    DEFAULT_SECRET_KEY,
    Settings,
    validate_runtime_config,
)


def test_local_anonymous_mode_is_allowed():
    config = Settings(
        _env_file=None,
        ENVIRONMENT="development",
        AUTH_REQUIRED=False,
        SECRET_KEY=DEFAULT_SECRET_KEY,
    )

    validate_runtime_config(config)


@pytest.mark.parametrize(
    "environment",
    ["production", "Production", " production ", "staging"],
)
def test_non_local_environment_rejects_disabled_auth(environment):
    config = Settings(
        _env_file=None,
        ENVIRONMENT=environment,
        AUTH_REQUIRED=False,
        SECRET_KEY="x" * 64,
    )

    with pytest.raises(RuntimeError, match="AUTH_REQUIRED"):
        validate_runtime_config(config)


@pytest.mark.parametrize("secret", ["", "   ", DEFAULT_SECRET_KEY, "short"])
def test_authenticated_runtime_rejects_unsafe_secret(secret):
    config = Settings(
        _env_file=None,
        ENVIRONMENT="production",
        AUTH_REQUIRED=True,
        SECRET_KEY=secret,
    )

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        validate_runtime_config(config)


def test_development_with_auth_enabled_still_requires_safe_secret():
    config = Settings(
        _env_file=None,
        ENVIRONMENT="development",
        AUTH_REQUIRED=True,
        SECRET_KEY=DEFAULT_SECRET_KEY,
    )

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        validate_runtime_config(config)


def test_unknown_environment_is_rejected_even_with_secure_values():
    config = Settings(
        _env_file=None,
        ENVIRONMENT="preview",
        AUTH_REQUIRED=True,
        SECRET_KEY="x" * 64,
    )

    with pytest.raises(RuntimeError, match="unsupported"):
        validate_runtime_config(config)


def test_safe_production_config_passes():
    config = Settings(
        _env_file=None,
        ENVIRONMENT="production",
        AUTH_REQUIRED=True,
        SECRET_KEY="x" * 64,
    )

    validate_runtime_config(config)
