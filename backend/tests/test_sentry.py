"""Sentry setup stays quiet unless production config turns it on."""

from types import SimpleNamespace

from app.core import sentry as sentry_module


def test_configure_sentry_noops_without_dsn(monkeypatch):
    calls = []
    fake_sdk = SimpleNamespace(init=lambda **kwargs: calls.append(kwargs))

    monkeypatch.setattr(sentry_module, "sentry_sdk", fake_sdk)
    monkeypatch.setattr(sentry_module.settings, "SENTRY_ENABLED", True)
    monkeypatch.setattr(sentry_module.settings, "SENTRY_DSN", "")

    sentry_module.configure_sentry()

    assert calls == []


def test_configure_sentry_uses_runtime_settings(monkeypatch):
    calls = []
    fake_sdk = SimpleNamespace(init=lambda **kwargs: calls.append(kwargs))

    monkeypatch.setattr(sentry_module, "sentry_sdk", fake_sdk)
    monkeypatch.setattr(sentry_module.settings, "SENTRY_ENABLED", True)
    monkeypatch.setattr(sentry_module.settings, "SENTRY_DSN", "https://public@example/1")
    monkeypatch.setattr(sentry_module.settings, "SENTRY_TRACES_SAMPLE_RATE", 0.25)
    monkeypatch.setattr(sentry_module.settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(sentry_module.settings, "PROJECT_NAME", "GraphMind")
    monkeypatch.setattr(sentry_module.settings, "VERSION", "0.1.0")
    monkeypatch.setattr(sentry_module.settings, "GIT_SHA", "abcdef1234567890")

    sentry_module.configure_sentry()

    assert calls[0]["dsn"] == "https://public@example/1"
    assert calls[0]["environment"] == "test"
    assert calls[0]["release"] == "GraphMind@0.1.0+abcdef123456"
    assert calls[0]["traces_sample_rate"] == 0.25
    assert calls[0]["send_default_pii"] is False


def test_sentry_release_falls_back_to_version(monkeypatch):
    monkeypatch.setattr(sentry_module.settings, "PROJECT_NAME", "GraphMind")
    monkeypatch.setattr(sentry_module.settings, "VERSION", "0.1.0")
    monkeypatch.setattr(sentry_module.settings, "GIT_SHA", "")

    assert sentry_module.sentry_release() == "GraphMind@0.1.0"


def test_capture_exception_adds_context(monkeypatch):
    captured = []
    extras = {}

    class FakeScope:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def set_extra(self, key, value):
            extras[key] = value

    fake_sdk = SimpleNamespace(
        new_scope=lambda: FakeScope(),
        capture_exception=lambda exc: captured.append(exc),
    )

    monkeypatch.setattr(sentry_module, "sentry_sdk", fake_sdk)
    monkeypatch.setattr(sentry_module.settings, "SENTRY_ENABLED", True)
    monkeypatch.setattr(sentry_module.settings, "SENTRY_DSN", "https://public@example/1")

    error = RuntimeError("boom")
    sentry_module.capture_exception(error, code="storage_failed", path="/api/v1/documents")

    assert captured == [error]
    assert extras == {"code": "storage_failed", "path": "/api/v1/documents"}
