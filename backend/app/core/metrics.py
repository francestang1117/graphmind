"""Prometheus metrics for the API surface."""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request, Response

from app.core.config import settings

log = logging.getLogger(__name__)

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
except ImportError:  # pragma: no cover - only used when the optional package is absent
    # A fresh clone may not have this installed yet; keep the API usable.
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4"
    Counter = Histogram = None  # type: ignore[assignment]
    generate_latest = None  # type: ignore[assignment]


METRICS_AVAILABLE = Counter is not None and Histogram is not None and generate_latest is not None

if METRICS_AVAILABLE:
    # Start with the numbers that are actually useful while debugging locally.
    HTTP_REQUESTS = Counter(
        "graphmind_http_requests_total",
        "Total HTTP requests handled by GraphMind.",
        ("method", "path", "status"),
    )
    HTTP_LATENCY = Histogram(
        "graphmind_http_request_duration_seconds",
        "HTTP request time in seconds.",
        ("method", "path"),
    )
    UPLOADS = Counter(
        "graphmind_uploads_total",
        "Document upload attempts grouped by result and extension.",
        ("result", "extension"),
    )
    UPLOAD_BYTES = Histogram(
        "graphmind_upload_bytes",
        "Uploaded file size in bytes.",
        ("extension",),
    )
    PIPELINE_RUNS = Counter(
        "graphmind_pipeline_runs_total",
        "Document processing pipeline runs.",
        ("status", "format"),
    )
    PIPELINE_LATENCY = Histogram(
        "graphmind_pipeline_duration_seconds",
        "Document processing pipeline time in seconds.",
        ("status", "format"),
    )
    SEARCHES = Counter(
        "graphmind_search_requests_total",
        "Search requests grouped by search type.",
        ("search_type",),
    )
    SEARCH_RESULTS = Histogram(
        "graphmind_search_results",
        "Number of results returned by a search request.",
        ("search_type",),
    )
    CHAT_REQUESTS = Counter(
        "graphmind_chat_requests_total",
        "Chat requests grouped by answer mode and streaming flag.",
        ("mode", "stream"),
    )
    CHAT_RESPONSE_CHARS = Histogram(
        "graphmind_chat_response_chars",
        "Length of non-streaming chat answers.",
        ("mode",),
    )


def configure_metrics(app: FastAPI) -> None:
    """Expose `/metrics` and record request-level timings."""
    if not settings.METRICS_ENABLED:
        return

    if not METRICS_AVAILABLE:
        log.warning("prometheus_client is not installed; metrics endpoint is disabled")

        @app.get("/metrics", include_in_schema=False)
        async def metrics_unavailable() -> Response:
            return Response("prometheus_client is not installed\n", status_code=503, media_type="text/plain")

        return

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        started_at = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            path = _route_path(request)
            # Use route patterns, not real filenames or hashes.
            HTTP_REQUESTS.labels(request.method, path, str(status)).inc()
            HTTP_LATENCY.labels(request.method, path).observe(time.perf_counter() - started_at)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def record_upload(result: str, filename: str, size_bytes: int = 0) -> None:
    if not METRICS_AVAILABLE or not settings.METRICS_ENABLED:
        return
    extension = _extension(filename)
    # File names stay out of metrics; extensions are enough here.
    UPLOADS.labels(result, extension).inc()
    if size_bytes > 0:
        UPLOAD_BYTES.labels(extension).observe(size_bytes)


def record_pipeline(status: str, fmt: str, duration_seconds: float) -> None:
    if not METRICS_AVAILABLE or not settings.METRICS_ENABLED:
        return
    label = fmt or "unknown"
    # PDFs and Markdown behave very differently, so keep the timing split.
    PIPELINE_RUNS.labels(status, label).inc()
    PIPELINE_LATENCY.labels(status, label).observe(max(duration_seconds, 0.0))


def record_search(search_type: str, result_count: int) -> None:
    if not METRICS_AVAILABLE or not settings.METRICS_ENABLED:
        return
    SEARCHES.labels(search_type).inc()
    SEARCH_RESULTS.labels(search_type).observe(result_count)


def record_chat(mode: str, stream: bool, answer: str = "") -> None:
    if not METRICS_AVAILABLE or not settings.METRICS_ENABLED:
        return
    mode_label = mode or "local"
    CHAT_REQUESTS.labels(mode_label, str(stream).lower()).inc()
    if not stream:
        # Short answers are often a sign that retrieval fell back.
        CHAT_RESPONSE_CHARS.labels(mode_label).observe(len(answer or ""))


def _route_path(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return str(path or request.url.path)


def _extension(filename: str) -> str:
    suffix = ""
    if "." in filename:
        suffix = filename.rsplit(".", 1)[-1].lower()
    return f".{suffix}" if suffix else "none"
