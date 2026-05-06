"""Rate-limit wrapper tests.

These focus on the parts that should stay true even when Redis/slowapi are not
available in local development: IP selection and the no-op decorator contract.
"""

from types import SimpleNamespace

from app.core import rate_limit
from app.core.config import settings


def _request(client_host: str, forwarded_for: str | None = None):
    headers = {}
    if forwarded_for:
        headers["X-Forwarded-For"] = forwarded_for
    return SimpleNamespace(client=SimpleNamespace(host=client_host), headers=headers)


def test_client_ip_uses_forwarded_for_only_from_trusted_proxy(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", ["10.0.0.10"])

    request = _request("10.0.0.10", "203.0.113.5, 10.0.0.10")

    assert rate_limit.get_client_ip(request) == "203.0.113.5"


def test_client_ip_ignores_forwarded_for_from_untrusted_client(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", ["10.0.0.10"])

    request = _request("198.51.100.9", "203.0.113.5")

    assert rate_limit.get_client_ip(request) == "198.51.100.9"


def test_noop_limiter_keeps_endpoint_callable():
    limiter = rate_limit.NoopLimiter()

    @limiter.limit("1/minute")
    def endpoint() -> str:
        return "ok"

    assert endpoint() == "ok"
